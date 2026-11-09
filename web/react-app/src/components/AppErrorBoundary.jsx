import { Component } from 'react'

// 화면 코드가 그리다 오류를 내면 React는 화면 전체를 지운다(하얀 화면).
// 그 대신 안내와 다시 불러오기 버튼을 보이고, 오류는 console.error 로 남긴다(원인 수정을 대신하지 않는 안전망).
export default class AppErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { failed: false }
  }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error, info) {
    console.error('[Provena] 화면 오류', error, info?.componentStack ?? '')
  }

  render() {
    if (!this.state.failed) return this.props.children
    const reload = this.props.onReload ?? (() => window.location.reload())
    return <main role="alert" className="status-page"><p>화면을 표시하는 중 문제가 생겼습니다. 화면을 다시 불러와 주세요.</p><button type="button" className="button button-dark" onClick={reload}>화면 다시 불러오기</button></main>
  }
}
