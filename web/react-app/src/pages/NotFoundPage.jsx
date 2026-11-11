import { Link } from 'react-router-dom'
import { useSession } from '../lib/session'

export default function NotFoundPage() {
  const { user } = useSession()
  return <main className="status-page" role="alert">
    <h1>페이지를 찾을 수 없습니다.</h1>
    <p>주소가 잘못되었거나 옮겨진 페이지입니다.</p>
    <Link className="button button-dark" to={user ? '/chat' : '/'}>{user ? '채팅으로 돌아가기' : '처음으로'}</Link>
  </main>
}
