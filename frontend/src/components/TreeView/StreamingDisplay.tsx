/**
 * Streaming display variants extracted from LinearView.
 * Handles single-stream, multi-stream with navigation, and "Thinking..." placeholder.
 * Also includes the stop generation button.
 */

import { ThinkingSection } from './ThinkingSection.tsx'
import './StreamingDisplay.css'

interface StreamingDisplayProps {
  isGenerating: boolean
  streamingContent: string
  streamingThinkingContent: string
  streamingContents: Record<number, string>
  streamingThinkingContents: Record<number, string>
  streamingNodeIds: Record<number, string>
  streamingTotal: number
  activeStreamIndex: number
  setActiveStreamIndex: (index: number) => void
  stopGeneration: () => void
}

export function StreamingDisplay({
  isGenerating,
  streamingContent,
  streamingThinkingContent,
  streamingContents,
  streamingThinkingContents,
  streamingNodeIds,
  streamingTotal,
  activeStreamIndex,
  setActiveStreamIndex,
  stopGeneration,
}: StreamingDisplayProps) {
  if (!isGenerating) return null

  const activeMultiContent = streamingContents[activeStreamIndex]

  return (
    <>
      {/* Multi-stream with branch navigation */}
      {streamingTotal > 1 && (
        <div className="message-row assistant">
          <div className="message-header-row">
            <div className="message-role">assistant</div>
            <div className="streaming-branch-nav">
              <button
                className="streaming-nav-arrow"
                onClick={() => setActiveStreamIndex(activeStreamIndex - 1)}
                disabled={activeStreamIndex <= 0}
              >
                &#8249;
              </button>
              <span className="streaming-nav-label">
                {activeStreamIndex + 1} of {streamingTotal}
              </span>
              <button
                className="streaming-nav-arrow"
                onClick={() => setActiveStreamIndex(activeStreamIndex + 1)}
                disabled={activeStreamIndex >= streamingTotal - 1}
              >
                &#8250;
              </button>
            </div>
          </div>
          {streamingThinkingContents[activeStreamIndex] && (
            <ThinkingSection
              thinkingContent={streamingThinkingContents[activeStreamIndex]}
              isStreaming={!streamingContents[activeStreamIndex]}
            />
          )}
          <div className="message-content">
            {activeMultiContent
              ? (
                <>
                  {activeMultiContent}
                  {!streamingNodeIds[activeStreamIndex] && (
                    <span className="streaming-cursor" />
                  )}
                </>
              )
              : streamingThinkingContents[activeStreamIndex]
                ? null
                : <span className="thinking">Thinking...</span>
            }
          </div>
        </div>
      )}

      {/* Single stream with content */}
      {streamingTotal <= 1 && (streamingContent || streamingThinkingContent) && (
        <div className="message-row assistant">
          <div className="message-role">assistant</div>
          {streamingThinkingContent && (
            <ThinkingSection
              thinkingContent={streamingThinkingContent}
              isStreaming={!streamingContent}
            />
          )}
          <div className="message-content">
            {streamingContent
              ? (
                <>
                  {streamingContent}
                  <span className="streaming-cursor" />
                </>
              )
              : streamingThinkingContent
                ? null
                : <span className="thinking">Thinking...</span>
            }
          </div>
        </div>
      )}

      {/* No content yet — just thinking placeholder */}
      {streamingTotal <= 1 && !streamingContent && !streamingThinkingContent && (
        <div className="message-row assistant">
          <div className="message-role">assistant</div>
          <div className="message-content thinking">Thinking...</div>
        </div>
      )}

      {/* Stop button */}
      <div className="stop-generation-row">
        <button className="stop-generation-btn" onClick={stopGeneration}>
          Stop generating
        </button>
      </div>
    </>
  )
}
