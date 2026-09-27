"""Guest portal: a small, separately exposed server that lets invited friends talk
to allowlisted models. Conversations are recorded as Qivis rhizomes.

Qivis itself is never exposed: the guest server talks to it over localhost and
offers each guest only their own conversations and the configured models.
"""
