function formatJoinedDate(value) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'numeric', day: 'numeric' }).format(new Date(value))
}

function roleLabel(item) {
  if (item.is_owner) return '최고 관리자'
  return item.role === 'admin' ? '관리자' : '일반 사용자'
}

export default function AdminUsersTable({ users, busyLoginId = '', onChangeRole }) {
  return <div className="admin-users-table-wrap"><table className="admin-users-table"><thead><tr><th>로그인 ID</th><th>역할</th><th>가입일</th><th>권한 관리</th></tr></thead><tbody>{users.map(item => <tr key={item.login_id}><td>{item.login_id}</td><td>{roleLabel(item)}</td><td>{formatJoinedDate(item.created_at)}</td><td>{item.is_owner ? <span>변경 불가</span> : <button type="button" className="reference-outline-button" disabled={busyLoginId === item.login_id} onClick={() => onChangeRole(item)}>{item.role === 'admin' ? '관리자 해제' : '관리자 지정'}</button>}</td></tr>)}</tbody></table></div>
}
