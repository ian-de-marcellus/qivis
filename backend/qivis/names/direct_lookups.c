/*
 * Next-token distributions straight from llama.cpp, for name searches
 * (qivis/names/direct.py builds this against llama-server's own libllama and
 * runs it in qivis/names/direct_worker.py).
 *
 * llama-server returns a full distribution as megabytes of JSON; here it
 * stays an array: a batch of token paths goes through the model at once, and
 * each output is reduced to what a name search reads (qivis.names.engine.
 * summarize): the tokens it can use above a floor, likeliest first, and how
 * much probability ends a word.
 */

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "llama.h"

typedef struct {
    struct llama_model *model;
    struct llama_context *ctx;
    const struct llama_vocab *vocab;
    int n_vocab;
    struct llama_batch batch;
    float *exps;
    int32_t *order;
} engine;

engine *eng_load(const char *path, int n_ctx, int n_seq, int n_batch) {
    llama_backend_init();
    struct llama_model_params mp = llama_model_default_params();
    mp.n_gpu_layers = 999;
    struct llama_model *model = llama_model_load_from_file(path, mp);
    if (!model) return NULL;
    struct llama_context_params cp = llama_context_default_params();
    cp.n_ctx = n_ctx;
    cp.n_batch = n_batch;
    cp.n_ubatch = n_batch;
    cp.n_seq_max = n_seq;
    cp.kv_unified = true; /* sequences share their prompt's cells */
    struct llama_context *ctx = llama_init_from_model(model, cp);
    if (!ctx) {
        llama_model_free(model);
        return NULL;
    }
    engine *e = calloc(1, sizeof(engine));
    e->model = model;
    e->ctx = ctx;
    e->vocab = llama_model_get_vocab(model);
    e->n_vocab = llama_vocab_n_tokens(e->vocab);
    e->batch = llama_batch_init(n_batch, 0, 1);
    e->exps = malloc(sizeof(float) * e->n_vocab);
    e->order = malloc(sizeof(int32_t) * e->n_vocab);
    return e;
}

void eng_free(engine *e) {
    llama_batch_free(e->batch);
    llama_free(e->ctx);
    llama_model_free(e->model);
    free(e->exps);
    free(e->order);
    free(e);
}

int eng_n_vocab(engine *e) { return e->n_vocab; }

/* As llama-server tokenizes a string prompt: its BOS if the model adds one,
   special tokens parsed. */
int eng_tokenize(engine *e, const char *text, int len, int32_t *out, int max) {
    return llama_tokenize(e->vocab, text, len, out, max, true, true);
}

int eng_piece(engine *e, int32_t id, char *buf, int len) {
    return llama_token_to_piece(e->vocab, id, buf, len, 0, true);
}

/* One decode: token i at position pos[i] in sequence seq[i]; want[i] asks for
   its distribution. Returns llama_decode's status (0: done). */
int eng_decode(engine *e, int n, const int32_t *tok, const int32_t *pos, const int32_t *seq,
               const int8_t *want) {
    e->batch.n_tokens = n;
    for (int i = 0; i < n; i++) {
        e->batch.token[i] = tok[i];
        e->batch.pos[i] = pos[i];
        e->batch.n_seq_id[i] = 1;
        e->batch.seq_id[i][0] = seq[i];
        e->batch.logits[i] = want[i];
    }
    return llama_decode(e->ctx, e->batch);
}

void eng_seq_cp(engine *e, int src, int dst, int p0, int p1) {
    llama_memory_seq_cp(llama_get_memory(e->ctx), src, dst, p0, p1);
}

void eng_seq_rm(engine *e, int seq, int p0, int p1) {
    llama_memory_seq_rm(llama_get_memory(e->ctx), seq, p0, p1);
}

static const float *sort_probs;

static int likelier(const void *a, const void *b) {
    int32_t x = *(const int32_t *)a, y = *(const int32_t *)b;
    if (sort_probs[x] != sort_probs[y]) return sort_probs[x] < sort_probs[y] ? 1 : -1;
    return x < y ? -1 : 1;
}

/* Batch output i, summarized: the softmax of its logits (plus `bias`, if
   given: the distribution sampling at temperature 1 would draw from); the
   tokens in `keep` above `floor`, likeliest first, into ids/probs; the mass
   of tokens not in `cont` (they end a word) and of those in `punct`.
   Returns how many tokens were kept, or -1 if there's no such output. */
int eng_summarize(engine *e, int i, const float *bias, const unsigned char *keep,
                  const unsigned char *cont, const unsigned char *punct, float floor,
                  int32_t *ids, float *probs, double *ends, double *punct_mass) {
    const float *logits = llama_get_logits_ith(e->ctx, i);
    if (!logits) return -1;
    int n = e->n_vocab;
    float *x = e->exps;
    float mx = -INFINITY;
    for (int t = 0; t < n; t++) {
        x[t] = logits[t] + (bias ? bias[t] : 0.0f);
        if (x[t] > mx) mx = x[t];
    }
    /* In double: a float sum of 100k terms drops the smallest, which are most
       of the word-continuing mass */
    double sum = 0.0;
    for (int t = 0; t < n; t++) {
        x[t] = expf(x[t] - mx);
        sum += x[t];
    }
    int k = 0;
    double en = 0.0, pu = 0.0;
    for (int t = 0; t < n; t++) {
        float q = (float)(x[t] / sum);
        x[t] = q;
        if (!cont[t]) en += q;
        if (punct[t]) pu += q;
        if (keep[t] && q > floor) e->order[k++] = t;
    }
    sort_probs = x;
    qsort(e->order, k, sizeof(int32_t), likelier);
    for (int j = 0; j < k; j++) {
        ids[j] = e->order[j];
        probs[j] = x[e->order[j]];
    }
    *ends = en;
    *punct_mass = pu;
    return k;
}
