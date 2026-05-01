function switchTab(tab) {
            document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
            document.querySelectorAll('.form-panel').forEach(function(p) { p.classList.remove('active'); });
            document.querySelector('.tab[onclick*="' + tab + '"]').classList.add('active');
            document.getElementById('panel-' + tab).classList.add('active');
            document.getElementById('error').style.display = 'none';
            document.getElementById('success').style.display = 'none';
        }

        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const errorEl = document.getElementById('error');
            const successEl = document.getElementById('success');
            const loginBtn = document.getElementById('loginBtn');

            errorEl.style.display = 'none';
            successEl.style.display = 'none';
            loginBtn.disabled = true;
            loginBtn.textContent = '\u767b\u5f55\u4e2d...';

            try {
                const resp = await fetch('/admin/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        username: document.getElementById('loginUsername').value,
                        password: document.getElementById('loginPassword').value
                    })
                });
                const result = await resp.json();

                if (result.success) {
                    window.location.href = '/admin';
                } else {
                    errorEl.textContent = result.message || '\u767b\u5f55\u5931\u8d25';
                    errorEl.style.display = 'block';
                }
            } catch (err) {
                errorEl.textContent = '\u7f51\u7edc\u9519\u8bef: ' + err.message;
                errorEl.style.display = 'block';
            } finally {
                loginBtn.disabled = false;
                loginBtn.textContent = '\u767b \u5f55';
            }
        });

        var countdownTimer = null;

        async function sendVerifyCode() {
            var btn = document.getElementById('sendCodeBtn');
            var email = document.getElementById('regEmail').value.trim();
            var errorEl = document.getElementById('error');
            var successEl = document.getElementById('success');
            errorEl.style.display = 'none';
            successEl.style.display = 'none';

            if (!email || email.indexOf('@') === -1) {
                errorEl.textContent = '\u8bf7\u8f93\u5165\u6709\u6548\u90ae\u7bb1';
                errorEl.style.display = 'block';
                return;
            }

            btn.disabled = true;
            var sec = 60;
            btn.textContent = sec + 's\u540e\u91cd\u53d1';
            countdownTimer = setInterval(function() {
                sec--;
                if (sec <= 0) {
                    clearInterval(countdownTimer);
                    btn.disabled = false;
                    btn.textContent = '\u53d1\u9001\u9a8c\u8bc1\u7801';
                } else {
                    btn.textContent = sec + 's\u540e\u91cd\u53d1';
                }
            }, 1000);

            try {
                var resp = await fetch('/admin/send-code', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({email: email})
                });
                var result = await resp.json();
                if (result.success) {
                    successEl.textContent = result.message;
                    successEl.style.display = 'block';
                } else {
                    errorEl.textContent = result.message;
                    errorEl.style.display = 'block';
                    clearInterval(countdownTimer);
                    btn.disabled = false;
                    btn.textContent = '\u53d1\u9001\u9a8c\u8bc1\u7801';
                }
            } catch (err) {
                errorEl.textContent = '\u53d1\u9001\u5931\u8d25: ' + err.message;
                errorEl.style.display = 'block';
                clearInterval(countdownTimer);
                btn.disabled = false;
                btn.textContent = '\u53d1\u9001\u9a8c\u8bc1\u7801';
            }
        }

        document.getElementById('registerForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            var errorEl = document.getElementById('error');
            var successEl = document.getElementById('success');
            var registerBtn = document.getElementById('registerBtn');

            errorEl.style.display = 'none';
            successEl.style.display = 'none';
            registerBtn.disabled = true;
            registerBtn.textContent = '\u6ce8\u518c\u4e2d...';

            try {
                var resp = await fetch('/admin/register', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        username: document.getElementById('regUsername').value,
                        password: document.getElementById('regPassword').value,
                        email: document.getElementById('regEmail').value,
                        code: document.getElementById('regCode').value
                    })
                });
                var result = await resp.json();

                if (result.success) {
                    successEl.textContent = result.message;
                    successEl.style.display = 'block';
                    clearInterval(countdownTimer);
                    setTimeout(function() { switchTab('login'); }, 1500);
                } else {
                    errorEl.textContent = result.message || '\u6ce8\u518c\u5931\u8d25';
                    errorEl.style.display = 'block';
                }
            } catch (err) {
                errorEl.textContent = '\u7f51\u7edc\u9519\u8bef: ' + err.message;
                errorEl.style.display = 'block';
            } finally {
                registerBtn.disabled = false;
                registerBtn.textContent = '\u6ce8 \u518c';
            }
        });