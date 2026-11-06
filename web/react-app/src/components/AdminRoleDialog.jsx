const ACTION_LABEL = { promote: '관리자로 지정', revoke: '관리자 권한을 해제' }

export default function AdminRoleDialog({ confirm, busy = false, onCancel, onConfirm }) {
  if (!confirm) return null
  const promoting = confirm.action === 'promote'
  const description = promoting
    ? '선택한 사용자에게 관리자 권한을 부여합니다.'
    : `${confirm.login_id}의 관리자 권한을 해제합니다.`
  const title = `${ACTION_LABEL[confirm.action]}하시겠습니까?`

  return <div className="approval-dialog" role="dialog" aria-modal="true"><section><h2>{title}</h2><p>{description}</p><div><button type="button" className="reference-outline-button" disabled={busy} onClick={onCancel}>취소</button><button type="button" className="button button-dark" disabled={busy} onClick={onConfirm}>확인</button></div></section></div>
}
