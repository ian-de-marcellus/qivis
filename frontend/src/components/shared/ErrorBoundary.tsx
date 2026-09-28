/**
 * Catches a rendering error in part of the app and shows it there, instead
 * of React unmounting everything (a blank page). Give it a `key` that
 * changes with what it shows, so moving elsewhere tries again.
 */

import { Component, type ReactNode } from 'react'
import './ErrorBoundary.css'

interface Props {
  what: string
  children: ReactNode
}

export class ErrorBoundary extends Component<Props, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error) {
    console.error(`[Qivis] ${this.props.what} failed to display`, error)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div className="error-boundary">
        <p>Something in {this.props.what} failed to display. Your data is unchanged.</p>
        <pre>{error.message}</pre>
        <button onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    )
  }
}
