import { useRef, useState } from 'react'
import { useTreeStore } from '../../store/treeStore.ts'
import './MessageInput.css'

export function MessageInput() {
  const { sendMessage, isGenerating, currentTree } = useTreeStore()
  const [content, setContent] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const canSend = content.trim().length > 0 && !isGenerating && currentTree != null

  const handleSend = () => {
    if (!canSend) return
    sendMessage(content.trim())
    setContent('')
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
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
          disabled={isGenerating || !currentTree}
          rows={1}
        />
        <button onClick={handleSend} disabled={!canSend}>
          Send
        </button>
      </div>
    </div>
  )
}
