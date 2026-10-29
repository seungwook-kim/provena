const loginIdInput = document.querySelector('#login-id');
const passwordInput = document.querySelector('#password');
const passwordToggle = document.querySelector('#password-toggle');
const message = document.querySelector('#form-message');
const loginButton = document.querySelector('#login-button');
const loginIdError = document.querySelector('#login-id-error');
const passwordError = document.querySelector('#password-error');
const logoutButton = document.querySelector('#logout-button');
let loginInProgress = false;

function showMessage(text, isLoading = false) {
  message.textContent = text;
  message.classList.toggle('is-loading', isLoading);
}

function setFieldError(input, errorElement, text) {
  errorElement.textContent = text;
  input.setAttribute('aria-invalid', String(Boolean(text)));
}

function getCookie(name) {
  const prefix = `${name}=`;
  const cookie = document.cookie.split('; ').find((item) => item.startsWith(prefix));
  return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : '';
}

function csrfHeaders() {
  const token = getCookie('provena_csrf');
  return token ? { 'X-CSRF-Token': token } : {};
}

async function issueCsrfToken() {
  const response = await fetch('/auth/csrf', {
    method: 'GET',
    credentials: 'same-origin',
  });
  if (response.status !== 204) {
    throw new Error('CSRF 토큰을 발급받지 못했습니다.');
  }

  const headers = csrfHeaders();
  if (!headers['X-CSRF-Token']) {
    throw new Error('CSRF 토큰을 확인하지 못했습니다.');
  }
  return headers;
}

function setLoggedInState(isLoggedIn) {
  logoutButton.hidden = !isLoggedIn;
  loginButton.disabled = isLoggedIn;
}

function clearPassword() {
  passwordInput.value = '';
}

function validateInputs() {
  const loginId = loginIdInput.value.trim();
  const password = passwordInput.value;
  const loginIdMissing = !loginId;
  const passwordMissing = !password;
  setFieldError(loginIdInput, loginIdError, loginIdMissing ? '로그인 ID를 입력해 주세요.' : '');
  setFieldError(passwordInput, passwordError, passwordMissing ? '비밀번호를 입력해 주세요.' : '');
  return { loginId, password, valid: !loginIdMissing && !passwordMissing };
}

passwordToggle.addEventListener('click', () => {
  const isVisible = passwordInput.type === 'text';
  passwordInput.type = isVisible ? 'password' : 'text';
  passwordToggle.textContent = isVisible ? '보기' : '숨기기';
  passwordToggle.setAttribute('aria-pressed', String(!isVisible));
});

async function login() {
  if (loginInProgress || !logoutButton.hidden) {
    return;
  }

  const values = validateInputs();
  showMessage('');
  if (!values.valid) {
    (values.loginId ? passwordInput : loginIdInput).focus();
    clearPassword();
    return;
  }

  loginInProgress = true;
  loginButton.disabled = true;
  showMessage('로그인 중입니다...', true);

  try {
    const csrf = await issueCsrfToken();
    const response = await fetch('/auth/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        ...csrf,
      },
      body: JSON.stringify({ login_id: values.loginId, password: values.password }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof body.detail === 'string' ? body.detail : '로그인에 실패했습니다.');
    }

    const meResponse = await fetch('/me', { credentials: 'same-origin' });
    if (!meResponse.ok) {
      throw new Error('로그인 상태를 확인하지 못했습니다.');
    }
    const user = await meResponse.json();
    setLoggedInState(true);
    showMessage(`로그인되었습니다. (${user.role})`);
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '서버 오류가 발생했습니다.');
  } finally {
    clearPassword();
    loginInProgress = false;
    if (!logoutButton.hidden) {
      loginButton.disabled = true;
    } else {
      loginButton.disabled = false;
    }
  }
}

loginButton.addEventListener('click', login);

for (const input of [loginIdInput, passwordInput]) {
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      login();
    }
  });
}

logoutButton.addEventListener('click', async () => {
  try {
    const response = await fetch('/auth/logout', {
      method: 'POST',
      credentials: 'same-origin',
      headers: csrfHeaders(),
    });
    if (!response.ok && response.status !== 204) {
      throw new Error('로그아웃에 실패했습니다.');
    }
    const meResponse = await fetch('/me', { credentials: 'same-origin' });
    if (meResponse.status !== 401) {
      throw new Error('로그아웃 상태를 확인하지 못했습니다.');
    }
    setLoggedInState(false);
    clearPassword();
    showMessage('로그아웃되었습니다.');
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '서버 오류가 발생했습니다.');
  }
});
