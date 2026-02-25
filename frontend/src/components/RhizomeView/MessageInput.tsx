import { useRef, useState } from 'react'
import { useRhizomeStore, useRhizomeData, useStreamingState } from '../../store/rhizomeStore.ts'
import './MessageInput.css'

export function MessageInput() {
  const { currentRhizome } = useRhizomeData()
  const { isGenerating } = useStreamingState()
  const sendMessage = useRhizomeStore(s => s.sendMessage)
  const sendMessageOnly = useRhizomeStore(s => s.sendMessageOnly)
  const [content, setContent] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const canSend = content.trim().length > 0 && !isGenerating && currentRhizome != null

  const resetInput = () => {
    setContent('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleSend = () => {
    if (!canSend) return
    sendMessage(content.trim())
    resetInput()
  }

  const handleSendOnly = () => {
    if (!canSend) return
    sendMessageOnly(content.trim())
    resetInput()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !(e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      handleSend()
    } else if (e.key === 'Enter' && !e.shiftKey && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      handleSendOnly()
    }
  }

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setContent(e.target.value)
    // Auto-grow
    const el = e.target
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }

  return (
    <div className="message-input">
      <div className="message-input-inner">
        <textarea
          ref={textareaRef}
          value={content}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={isGenerating ? 'Generating...' : 'Type a message...'}
          disabled={isGenerating || !currentRhizome}
          rows={1}
        />
        <button onClick={handleSend} disabled={!canSend}>
          Send
        </button>
        <button
          className="send-only-btn"
          onClick={handleSendOnly}
          disabled={!canSend}
          title="Send without generating a response (Cmd+Enter)"
        >
          No gen
        </button>
      </div>
    </div>
  )
}
