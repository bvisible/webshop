//// Neoffice — added file (no upstream equivalent). The sign-in / create-account
//// dialog of the shop. Upstream sends the visitor to /login and back, which loses
//// the cart and the step the buyer was on; this signs them in in place, over the
//// same endpoints (3bc2d836f1, 2025-02-11; existing-user handling 428f770c19,
//// 2026-04-08 "handle existing users in shop create_account (WI-00297)").
frappe.showLoginDialog = function(opts) {
    if (!opts) opts = {};
    const forceLogin = opts.forceLogin || false;

    if (frappe.session.user !== 'Guest') {
        // If user is already logged in
        const dialogHTML = `
            <div class="login-dialog-overlay">
                <div class="login-dialog">
                    <div class="login-dialog-header">
                        <h3><span class="wave-emoji">👋</span> ${__('Hello')} <span class="user-name">${frappe.full_name || frappe.session.user}!</span></h3>
                        ${!forceLogin ? '<button class="close-btn">&times;</button>' : ''}
                    </div>
                    <div class="login-dialog-content">
                        ${forceLogin ? `<p class="text-center mb-4">${__('Please log in to continue with checkout')}</p>` : ''}
                        <div class="form-group text-center">
                            <p>${__('You are already logged in.')}</p>
                            <p>${__('Redirecting to your account in')} <span class="countdown">3</span> ${__('seconds')}...</p>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const dialogContainer = document.createElement('div');
        dialogContainer.innerHTML = dialogHTML;
        document.body.appendChild(dialogContainer);

        // Apply styles
        const styles = document.createElement('style');
        styles.textContent = `
            .login-dialog-overlay {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.5);
                display: flex;
                justify-content: center;
                align-items: center;
                z-index: 1050;
            }

            .login-dialog {
                background: white;
                border-radius: 8px;
                padding: 20px;
                width: 90%;
                max-width: 400px;
                position: relative;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            }

            .login-dialog-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
            }

            .login-dialog-header h3 {
                margin: 0;
                font-size: 1.5em;
            }

            .close-btn {
                background: none;
                border: none;
                font-size: 24px;
                cursor: pointer;
                padding: 0;
                color: #666;
            }

            .close-btn:hover {
                color: #333;
            }

            .login-dialog-content {
                text-align: center;
            }

            .countdown {
                font-weight: bold;
                color: var(--primary-color);
            }
        `;
        document.head.appendChild(styles);

        // Handle countdown and redirection
        let countdown = 3;
        const countdownElement = dialogContainer.querySelector('.countdown');
        const countdownInterval = setInterval(() => {
            countdown--;
            countdownElement.textContent = countdown;
            if (countdown === 0) {
                clearInterval(countdownInterval);
                window.location.href = '/me';
            }
        }, 1000);

        // Handle closing
        const closeBtn = dialogContainer.querySelector('.close-btn');
        if (closeBtn) {
            closeBtn.addEventListener('click', function() {
                clearInterval(countdownInterval);
                dialogContainer.remove();
            });
        }

        return;
    }

    // Create dialog HTML
    //// Neoffice — a dialog for assistive technology and browsing agents: its role, a title, named
    //// buttons, autofill tokens, the password toggle as a keyboard button, the page behind inert
    //// (below), Escape and a click on the backdrop to close when the sign-in is not forced (#691 lot 4).
    const dialogHTML = `
        <div class="login-dialog-overlay">
            <div class="login-dialog" role="dialog" aria-modal="true" aria-labelledby="login-dialog-title">
                <div class="login-dialog-header">
                    <div class="welcome-header d-flex justify-content-between">
                        <h3 id="login-dialog-title"><span class="wave-emoji" aria-hidden="true">👋</span> ${__('Hello')} <span class="user-name"></span></h3>
                        ${!forceLogin ? `<button type="button" class="close-btn" aria-label="${__('Close')}">&times;</button>` : ''}
                    </div>
                </div>
                <p class="welcome-text">${__('Enter your email address to sign in or create an account')}</p>
                <div class="login-dialog-body">
                    <div class="form-group slide-in">
                        <label for="login_email">${__('Email')}</label>
                        <div class="email-field">
                            <input type="email" id="login_email" class="form-control" autocomplete="email"
                                placeholder="${__('jane@example.com')}" required>
                            <button type="button" class="btn-verify-email" aria-label="${__('Continue')}">
                                <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M13.75 6.75L19.25 12L13.75 17.25" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                                    <path d="M19 12H4.75" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                            </button>
                            <svg class="field-icon email-icon" aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none"
                                xmlns="http://www.w3.org/2000/svg">
                                <path d="M2 6.12119V12.0606C2 12.35 2.115 12.6274 2.31967 12.832C2.52433 13.0367 2.80165 13.1517 3.09091 13.1517H12.9091C13.1984 13.1517 13.4757 13.0367 13.6804 12.832C13.885 12.6274 14 12.35 14 12.0606V6.12119M14 6.06058V4.42421C14 4.13488 13.885 3.85741 13.6804 3.65282C13.4757 3.44823 13.1984 3.3333 12.9091 3.3333H3.09091C2.80165 3.3333 2.52433 3.44823 2.31967 3.65282C2.115 3.85741 2 4.13488 2 4.42421V6.06058L8 8.66664L14 6.06058Z" stroke="currentColor" stroke-width="1.5"/>
                            </svg>
                        </div>
                    </div>
                    <!-- //// Neoffice — where the shop signs in with a code, the password is one tap away from the first step too:
                         a mail that does not come must never lock anybody out (neoffice-maintenance#2192) -->
                    <p class="email-step-links" style="display: none;"><a href="#" class="email-use-password">${__('Use my password')}</a></p>
                    <div class="form-group password-section slide-in" style="display: none;">
                        <label for="login_password">${__('Password')}</label>
                        <div class="password-field">
                            <input type="password" id="login_password" class="form-control" autocomplete="current-password"
                                placeholder="•••••">
                            <svg class="field-icon password-icon" aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none"
                                xmlns="http://www.w3.org/2000/svg">
                                <path d="M4.5 7.5V5.5C4.5 4.30653 5.30653 3.5 6.5 3.5H9.5C10.6935 3.5 11.5 4.30653 11.5 5.5V7.5M6.5 9.5L8 11M8 11L9.5 12.5M8 11L9.5 9.5M8 11L6.5 12.5M4 7.5H12C12.5523 7.5 13 7.94772 13 8.5V13.5C13 14.0523 12.5523 14.5 12 14.5H4C3.44772 14.5 3 14.0523 3 13.5V8.5C3 7.94772 3.44772 7.5 4 7.5Z" stroke="currentColor" stroke-width="1.5"/>
                            </svg>
                            <span toggle="#login_password" class="toggle-password text-muted" role="button" tabindex="0" aria-controls="login_password">${__('Show')}</span>
                        </div>
                        <p class="forgot-password-message">
                            <a href="/login#forgot">${__('Forgot Password?')}</a>
                        </p>
                    </div>
                    <!-- //// Neoffice — step two of signing in with a code (frappe.passwordless): the code the mail carries -->
                    <div class="form-group code-section slide-in" style="display: none;">
                        <p class="code-intro text-muted"></p>
                        <label for="login_code">${__('Code')}</label>
                        <input type="text" id="login_code" class="form-control" inputmode="numeric"
                            autocomplete="one-time-code" pattern="[0-9 ]*" maxlength="7" placeholder="000000">
                        <p class="code-links">
                            <a href="#" class="code-resend">${__('Send a new code')}</a>
                            &middot;
                            <a href="#" class="code-use-password">${__('Use my password')}</a>
                        </p>
                    </div>
                    <div class="form-group fullname-section slide-in" style="display: none;">
                        <div class="form-group">
                            <label for="first_name">${__('First Name')}</label>
                            <input type="text" id="first_name" class="form-control" autocomplete="given-name" required>
                        </div>
                        <div class="form-group">
                            <label for="last_name">${__('Last Name')}</label>
                            <input type="text" id="last_name" class="form-control" autocomplete="family-name" required>
                        </div>
                    </div>
                </div>
                <div class="login-dialog-footer slide-in" style="display: none;">
                    <button type="button" class="btn btn-primary btn-submit">${__('Continue')}</button>
                </div>
                <div class="social-logins slide-in" style="display: none;">
                    <div class="social-login-buttons">
                    </div>
                    <div class="login-with-email-link" style="display: none;">
                        <p class="text-muted login-divider">${__('or')}</p>
                        <div class="login-button-wrapper">
                            <a href="#login-with-email-link" class="btn btn-default btn-login-with-email-link">
                                ${__('Send login link')}
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Add CSS
    if (!document.getElementById('login-dialog-styles')) {
        const styles = document.createElement('style');
        styles.id = 'login-dialog-styles';
        styles.textContent = `
            .login-dialog-overlay {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.5);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 1050;
                opacity: 0;
                transition: opacity 0.3s ease;
            }
            .login-dialog-overlay.show {
                opacity: 1;
            }
            .login-dialog {
                background: white;
                border-radius: 8px;
                width: 90%;
                max-width: 400px;
                padding: 20px;
                box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
                transform: translateY(20px);
                opacity: 0;
                transition: all 0.3s ease;
            }
            .login-dialog.show {
                transform: translateY(0);
                opacity: 1;
            }
            .slide-in {
                transform: translateY(10px);
                opacity: 0;
                transition: all 0.3s ease;
            }
            .slide-in.show {
                transform: translateY(0);
                opacity: 1;
            }
            .login-dialog-header {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                margin-bottom: 20px;
            }
            .welcome-header {
                flex: 1;
            }
            .welcome-header h3 {
                font-size: 30px;
                margin: 0 0 10px 0;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .wave-emoji {
                display: inline-block;
                animation: wave 2s infinite;
                animation-play-state: paused;
            }
            .wave-emoji.waving {
                animation-play-state: running;
            }
            @keyframes wave {
                0% { transform: rotate(0deg); }
                10% { transform: rotate(-10deg); }
                20% { transform: rotate(12deg); }
                30% { transform: rotate(-10deg); }
                40% { transform: rotate(9deg); }
                50% { transform: rotate(0deg); }
                100% { transform: rotate(0deg); }
            }
            .welcome-text {
                color: #666;
                margin: 0;
                font-size: 14px;
                line-height: 1.4;
            }
            .close-btn {
                background: none;
                border: none;
                font-size: 24px;
                cursor: pointer;
                padding: 0;
                margin-left: 10px;
            }
            .form-group {
                margin-bottom: 15px;
            }
            .form-group label {
                display: block;
                margin-bottom: 5px;
            }
            .email-field {
                position: relative;
                display: flex;
                gap: 0px;
            }
            .email-field input {
                flex: 1;
                padding-left: 35px;
                border-radius: 4px 0 0 4px;
                height: 42px;
                background: transparent;
                border: 1px solid;
            }
            .btn-verify-email {
                padding: 4px 8px;
                background: var(--btn-primary);
                color: var(--neutral);
                white-space: nowrap;
                --icon-stroke: currentColor;
                --icon-fill-bg: var(--btn-primary);
                border: none;
                border-radius: 0 4px 4px 0;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.3s ease;
            }
            .btn-verify-email:hover {
                background: #3311CC;
                transform: translateX(2px);
            }
            .field-icon {
                position: absolute;
                left: 10px;
                top: 50%;
                transform: translateY(-50%);
                color: #74808B;
            }
            .password-field {
                position: relative;
            }
            .password-field input {
                padding-left: 35px;
                padding-right: 50px;
            }
            .password-field.shake {
                animation: shake 0.5s cubic-bezier(.36,.07,.19,.97) both;
                transform: translate3d(0, 0, 0);
            }
            @keyframes shake {
                10%, 90% {
                    transform: translate3d(-1px, 0, 0);
                }
                20%, 80% {
                    transform: translate3d(2px, 0, 0);
                }
                30%, 50%, 70% {
                    transform: translate3d(-3px, 0, 0);
                }
                40%, 60% {
                    transform: translate3d(3px, 0, 0);
                }
            }
            .toggle-password {
                position: absolute;
                right: 10px;
                top: 50%;
                transform: translateY(-50%);
                cursor: pointer;
                color: #666;
            }
            .login-dialog-footer {
                margin-top: 20px;
            }
            .btn-submit {
                width: 100%;
                padding: 10px;
                border: none;
                border-radius: 4px;
                background: #4318FF;
                color: white;
                font-weight: bold;
                cursor: pointer;
                transition: background 0.3s ease;
            }
            .btn-submit:hover {
                background: #3311CC;
            }
            .social-logins {
                margin-top: 20px;
                text-align: center;
            }
            .login-divider {
                display: flex;
                align-items: center;
                margin: 15px 0;
            }
            .login-divider:before,
            .login-divider:after {
                content: '';
                flex: 1;
                border-top: 1px solid #ddd;
            }
            .login-divider:before {
                margin-right: 10px;
            }
            .login-divider:after {
                margin-left: 10px;
            }
            .social-login-buttons {
                display: flex;
                flex-direction: column;
                gap: 10px;
            }
            .btn-default {
                width: 100%;
                padding: 8px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background: white;
                color: #444;
                text-decoration: none;
                text-align: center;
                transition: background 0.3s ease;
            }
            .btn-default:hover {
                background: #f5f5f5;
            }
            .login-dialog-header:not(:has(.close-btn)) {
                flex-direction: column;
                align-items: flex-start;
            }
            .lds-ring,
            .lds-ring div {
                box-sizing: border-box;
            }
            .lds-ring {
                display: inline-block;
                position: relative;
                width: 13px;
                height: 13px;
            }
            .lds-ring div {
                box-sizing: border-box;
                display: block;
                position: absolute;
                width: 15px;
                height: 15px;
                margin: 0px;
                border: 2px solid currentColor;
                border-radius: 50%;
                animation: lds-ring 1.2s cubic-bezier(0.5, 0, 0.5, 1) infinite;
                border-color: currentColor transparent transparent transparent;
            }
            .lds-ring div:nth-child(1) {
                animation-delay: -0.45s;
            }
            .lds-ring div:nth-child(2) {
                animation-delay: -0.3s;
            }
            .lds-ring div:nth-child(3) {
                animation-delay: -0.15s;
            }
            @keyframes lds-ring {
            0% {
                transform: rotate(0deg);
            }
            100% {
                transform: rotate(360deg);
            }
            }


        `;
        document.head.appendChild(styles);
    }

    // Add dialog to DOM
    const dialogContainer = document.createElement('div');
    dialogContainer.innerHTML = dialogHTML;
    document.body.appendChild(dialogContainer);

    //// Neoffice — the page behind a modal is inert while it is open: the keyboard, a screen reader
    //// and an agent reading the accessibility tree reached the page under the overlay (#691 lot 4).
    //// Frappe's own dialogs and toasts stay live: a message shown during the sign-in must be closable.
    const madeInert = [...document.body.children].filter(
        (el) => el !== dialogContainer && !el.inert && !['SCRIPT', 'STYLE', 'LINK'].includes(el.tagName)
            && !el.matches('.modal, .modal-backdrop, #alert-container, [role="dialog"], [aria-modal]')
    );
    madeInert.forEach((el) => { el.inert = true; });

    // Get elements
    const dialog = dialogContainer.querySelector('.login-dialog-overlay');
    const dialogBox = dialog.querySelector('.login-dialog');
    const emailInput = dialog.querySelector('#login_email');
    const passwordSection = dialog.querySelector('.password-section');
    const fullnameSection = dialog.querySelector('.fullname-section');
    const passwordInput = dialog.querySelector('#login_password');
    const firstNameInput = dialog.querySelector('#first_name');
    const lastNameInput = dialog.querySelector('#last_name');
    const submitBtn = dialog.querySelector('.btn-submit');
    const verifyBtn = dialog.querySelector('.btn-verify-email');
    const closeBtn = dialog.querySelector('.close-btn');
    const dialogFooter = dialog.querySelector('.login-dialog-footer');
    const togglePassword = dialog.querySelector('.toggle-password');
    const waveEmoji = dialog.querySelector('.wave-emoji');
    const socialLogins = dialog.querySelector('.social-logins');
    const socialLoginButtons = dialog.querySelector('.social-login-buttons');
    const loginWithEmailLink = dialog.querySelector('.login-with-email-link');
    const userName = dialog.querySelector('.user-name');
    const codeSection = dialog.querySelector('.code-section');
    const codeInput = dialog.querySelector('#login_code');
    const codeIntro = dialog.querySelector('.code-intro');
    const resendLink = dialog.querySelector('.code-resend');
    const usePasswordLink = dialog.querySelector('.code-use-password');
    const emailStepLinks = dialog.querySelector('.email-step-links');
    const emailUsePassword = dialog.querySelector('.email-use-password');

    // Function to validate email
    function isValidEmail(email) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return emailRegex.test(email);
    }

    // Show dialog with animation
    requestAnimationFrame(() => {
        dialog.classList.add('show');
        dialogBox.classList.add('show');
        dialog.querySelector('.form-group').classList.add('show');
    });

    // Get social login providers and email link settings
    frappe.call({
        method: 'webshop.webshop.auth.api.get_auth_settings',
        callback: function(r) {
            if (r.message) {
                const { social_login, login_with_email_link, provider_logins } = r.message;
                passwordless = !!r.message.passwordless;
                showEmailStepLinks(codeSection.style.display !== 'block' && passwordSection.style.display !== 'block');

                if (social_login || login_with_email_link) {
                    socialLogins.style.display = 'block';
                    setTimeout(() => socialLogins.classList.add('show'), 50);
                    
                    if (provider_logins && provider_logins.length) {
                        provider_logins.forEach(provider => {
                            const button = document.createElement('div');
                            button.className = 'login-button-wrapper';
                            button.innerHTML = `
                                <a href="${provider.auth_url}" 
                                   class="btn btn-default btn-login-option btn-${provider.name}">
                                    ${provider.icon || ''}
                                    ${__('Login with {0}', [provider.provider_name])}
                                </a>
                            `;
                            socialLoginButtons.appendChild(button);
                        });
                    }
                }
            }
        }
    });

    // Animate emoji every 10 seconds
    function startWaveAnimation() {
        waveEmoji.classList.add('waving');
        setTimeout(() => {
            waveEmoji.classList.remove('waving');
        }, 2000);
    }
    startWaveAnimation();
    const waveInterval = setInterval(startWaveAnimation, 10000);

    // Handle closing
    function closeDialog() {
        madeInert.forEach((el) => { el.inert = false; });
        document.removeEventListener('keydown', closeOnEscape);
        clearInterval(waveInterval);
        dialog.classList.remove('show');
        dialogBox.classList.remove('show');
        setTimeout(() => {
            document.body.removeChild(dialogContainer);
        }, 300);
        if (opts.callback) opts.callback();
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            if (!forceLogin) {
                closeDialog();
            }
        });
    }

    // If forceLogin is true, prevent closing by clicking overlay
    //// Neoffice — `dialog` IS the overlay: looking for an overlay inside it found nothing, so a
    //// click on the backdrop never closed the dialog. Escape closes it too (#691 lot 4).
    if (!forceLogin) {
        dialog.addEventListener('click', function(e) {
            if (e.target === dialog) {
                closeDialog();
            }
        });
    }
    function closeOnEscape(e) {
        if (e.key === 'Escape' && !forceLogin) closeDialog();
    }
    document.addEventListener('keydown', closeOnEscape);

    // Toggle password visibility
    if (togglePassword && passwordInput) {
        togglePassword.addEventListener('click', function() {
            const type = passwordInput.type === 'password' ? 'text' : 'password';
            passwordInput.type = type;
            togglePassword.textContent = type === 'password' ? __('Show') : __('Hide');
        });
        //// Neoffice — a role="button": Enter and Space press it (#691 lot 4)
        togglePassword.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                togglePassword.click();
            }
        });
    }

    // Show section with animation
    function showSection(section) {
        section.style.display = 'block';
        requestAnimationFrame(() => {
            section.classList.add('show');
        });
    }

    //// Neoffice — signing in with a code (`frappe.passwordless` in the frappe fork, `auth/code_sign_in.py`,
    //// neoffice-maintenance#2192): the address, then the code the mail carries, then the page the buyer was on.
    //// An address with no account comes back with the proof of its mailbox and is asked its name. The password
    //// stays behind "Use my password". Off (or stock frappe) none of this runs.
    let passwordless = false;
    let codeEmail = '';
    let signUpProof = null;
    let resendTimer = null;
    let requestingCode = false;
    const spinnerHtml = '<div class="lds-ring"><div></div><div></div><div></div><div></div></div>';

    // The shop's own fetch, never frappe.call: on a 429 frappe.call never calls its error callback and pops a
    // Frappe dialog over the page, and the buyer stays on a spinner.
    function postJSON(method, args) {
        const body = Object.assign({}, args);
        if (window.webshop_content_language) body._lang = window.webshop_content_language;
        return fetch('/api/method/' + method, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-Frappe-CSRF-Token': frappe.csrf_token || window.csrf_token || '',
            },
            body: JSON.stringify(body),
        }).then((response) => response.json().catch(() => ({})).then((json) => ({
            status: response.status,
            body: json.message || {},
        })));
    }

    function alertRed(message) {
        frappe.show_alert({ message: message, indicator: 'red' });
    }

    function startResendCountdown(seconds) {
        clearInterval(resendTimer);
        let left = seconds;
        resendLink.style.pointerEvents = 'none';
        resendLink.style.opacity = '0.5';
        resendTimer = setInterval(() => {
            left -= 1;
            if (left <= 0) {
                clearInterval(resendTimer);
                resendLink.style.pointerEvents = '';
                resendLink.style.opacity = '';
            }
        }, 1000);
    }

    function leave(target) {
        closeDialog();
        const here = window.location.pathname + window.location.search;
        if (!target || target === here) window.location.reload();
        else window.location.assign(target);
    }

    //// Neoffice — the password, whatever happens: a code that does not arrive (no mail, a refused request, a
    //// network failure, a locked or barred account) must never leave anybody stuck on a red message. The link
    //// under the address and the one under the code both come here, and so does every failure of the mail.
    function showEmailStepLinks(show) {
        emailStepLinks.style.display = show && passwordless ? 'block' : 'none';
    }

    function usePassword() {
        clearInterval(resendTimer);
        codeSection.style.display = 'none';
        fullnameSection.style.display = 'none';
        showEmailStepLinks(false);
        showSection(passwordSection);
        showSection(dialogFooter);
        submitBtn.textContent = __('Sign in');
        passwordInput.focus();
    }

    function resetToEmail() {
        clearInterval(resendTimer);
        signUpProof = null;
        [codeSection, passwordSection, fullnameSection, dialogFooter].forEach((el) => { el.style.display = 'none'; });
        showEmailStepLinks(true);
        emailInput.focus();
    }

    function showCodeStep(email, resendIn, resend) {
        codeEmail = email;
        signUpProof = null;
        passwordSection.style.display = 'none';
        fullnameSection.style.display = 'none';
        showEmailStepLinks(false);
        codeIntro.textContent = __('We sent a code to {0}. Enter it to continue.', [email]);
        codeInput.value = '';
        showSection(codeSection);
        submitBtn.textContent = __('Sign in');
        showSection(dialogFooter);
        codeInput.focus();
        startResendCountdown(resendIn);
        if (resend) frappe.show_alert({ message: __('A new code is on its way.'), indicator: 'green' });
    }

    function askForCode(email, resend) {
        if (requestingCode) return;
        requestingCode = true;
        verifyBtn.disabled = true;
        verifyBtn.classList.add('loading');
        postJSON('frappe.passwordless.request_code', {
            email: email,
            redirect_to: window.location.pathname + window.location.search,
        }).then((res) => {
            if (res.status === 429) {
                alertRed(__('Too many requests. Please try again later.'));
                return usePassword();
            }
            if (!res.body.ok) {
                if (res.body.reason === 'invalid_address') return alertRed(__('Please enter a valid email address'));
                if (res.body.reason === 'disabled') {
                    // the site stopped offering the code since the page loaded: the ordinary sign-in takes over
                    passwordless = false;
                    showEmailStepLinks(false);
                    return verifyEmail();
                }
                alertRed(__('An error occurred'));
                return usePassword();
            }
            showCodeStep(email, res.body.resend_in || 30, resend);
        }).catch(() => {
            alertRed(__('An error occurred'));
            usePassword();
        }).finally(() => {
            requestingCode = false;
            verifyBtn.disabled = false;
            verifyBtn.classList.remove('loading');
        });
    }

    function verifyCode() {
        const code = codeInput.value.replace(/\s+/g, '');
        if (!/^\d{6}$/.test(code)) {
            alertRed(__('This code is not valid. Check it and try again.'));
            codeInput.focus();
            return;
        }
        const original = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = spinnerHtml;
        postJSON('frappe.passwordless.verify_code', { email: codeEmail, code: code }).then((res) => {
            const r = res.body;
            if (res.status === 429) return alertRed(__('Too many requests. Please try again later.'));
            if (r.ok && r.status === 'signed_in') {
                frappe.show_alert({ message: __('Successful connection!'), indicator: 'green' });
                return leave(r.redirect_to);
            }
            if (r.ok && r.status === 'unknown_address') {
                signUpProof = r.proof;
                clearInterval(resendTimer);
                codeSection.style.display = 'none';
                showSection(fullnameSection);
                submitBtn.textContent = __('Create account');
                frappe.show_alert({
                    message: __('Your email is confirmed. Tell us your name to create your account.'),
                    indicator: 'green',
                });
                return firstNameInput.focus();
            }
            alertRed({
                locked: __('Too many wrong codes. Ask for a new code.'),
                not_allowed: __('Signing in with a code is not available for this account. Use your password.'),
            }[r.reason] || __('This code is not valid. Check it and try again.'));
            if (r.reason === 'not_allowed') return usePassword();
            codeInput.value = '';
            codeInput.focus();
        }).catch(() => {
            alertRed(__('An error occurred'));
        }).finally(() => {
            submitBtn.disabled = false;
            if (submitBtn.innerHTML === spinnerHtml) submitBtn.innerHTML = original;
        });
    }

    function completeSignUp(firstName, lastName) {
        const original = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = spinnerHtml;
        postJSON('webshop.webshop.auth.code_sign_in.complete_sign_up', {
            proof: signUpProof,
            first_name: firstName,
            last_name: lastName,
            redirect_to: window.location.pathname + window.location.search,
        }).then((res) => {
            const r = res.body;
            if (r.message === 'success' && r.signed_in) {
                // the notice is translated by the server: a website page resolves no new __() string
                try { sessionStorage.setItem('webshop_account_opened', r.notice || ''); } catch (e) { /* private mode */ }
                return leave(r.redirect_to);
            }
            if (res.status === 429) return alertRed(__('Too many requests. Please try again later.'));
            alertRed(r.reason || __('An error occurred'));
            if (r.reason_code === 'invalid_proof') resetToEmail();
        }).catch(() => {
            alertRed(__('An error occurred'));
        }).finally(() => {
            submitBtn.disabled = false;
            if (submitBtn.innerHTML === spinnerHtml) submitBtn.innerHTML = original;
        });
    }

    resendLink.addEventListener('click', function(e) {
        e.preventDefault();
        askForCode(codeEmail, true);
    });
    usePasswordLink.addEventListener('click', function(e) {
        e.preventDefault();
        usePassword();
    });
    //// Neoffice — from the first step: no mail is asked for, the person who already knows their password signs in
    emailUsePassword.addEventListener('click', function(e) {
        e.preventDefault();
        if (!isValidEmail(emailInput.value.trim())) {
            frappe.show_alert({message: __('Please enter a valid email address'), indicator: 'red'});
            emailInput.focus();
            return;
        }
        usePassword();
    });
    codeInput.addEventListener('input', function() {
        if (codeInput.value.replace(/\s+/g, '').length === 6) verifyCode();
    });
    codeInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            verifyCode();
        }
    });

    // Verify email function
    function verifyEmail() {
        const email = emailInput.value.trim();
        
        // Check if email is valid
        if (!isValidEmail(email)) {
            frappe.show_alert({
                message: __("Please enter a valid email address"),
                indicator: 'red'
            });
            emailInput.focus();
            return;
        }

        //// Neoffice — where the shop signs in with a code, the address is not looked up (it would tell a known
        //// address from an unknown one): the code is asked for, the same for everybody.
        if (passwordless) {
            askForCode(email, false);
            return;
        }

        verifyBtn.disabled = true;
        verifyBtn.classList.add('loading');

        frappe.call({
            method: 'webshop.webshop.auth.api.check_email',
            args: { email: email },
            callback: function(r) {
                verifyBtn.disabled = false;
                verifyBtn.classList.remove('loading');

                if (r.message && r.message.exists) {
                    showSection(passwordSection);
                    passwordInput.focus(); 
                    fullnameSection.style.display = 'none';
                    submitBtn.textContent = __('Sign in');
                    // Update Hello with first name
                    if (r.message.first_name) {
                        userName.textContent = " " + r.message.first_name + "!";
                    }
                    // Show login with email link if user exists
                    if (r.message.login_with_email_link) {
                        loginWithEmailLink.style.display = 'block';
                        setTimeout(() => loginWithEmailLink.classList.add('show'), 50);
                    }
                } else {
                    showSection(fullnameSection);
                    passwordSection.style.display = 'none';
                    submitBtn.textContent = __('Create account');
                    // Reset Hello
                    userName.textContent = "!";
                    // Hide login with email link for new users
                    loginWithEmailLink.style.display = 'none';
                    loginWithEmailLink.classList.remove('show');
                    // Focus on first_name field
                    firstNameInput.focus();
                }
                showSection(dialogFooter);
            }
        });
    }

    // Add verify button click handler
    verifyBtn.addEventListener('click', verifyEmail);

    // Add email input blur handler
    emailInput.addEventListener('blur', function() {
        //// Neoffice — a code is mailed only on Continue or Enter, never because the field lost the focus
        if (passwordless) return;
        const email = emailInput.value.trim();
        if (email) {
            verifyEmail();
        }
    });

    // Add email input enter key handler
    emailInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            verifyEmail();
        }
    });

    // Add keypress event on password field
    passwordInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            dialog.querySelector('.btn-submit').click();
        }
    });

    // Handle form submission
    dialog.querySelector('.btn-submit').addEventListener('click', function() {
        //// Neoffice — step two of the code sign-in is on screen: the button sends the code
        if (codeSection.style.display === 'block') {
            verifyCode();
            return;
        }
        const email = emailInput.value.trim();
        const password = passwordInput.value;
        const firstName = firstNameInput.value.trim();
        const lastName = lastNameInput.value.trim();

        if (!email) {
            frappe.show_alert({message: __('Please enter your email address'), indicator: 'red'});
            return;
        }

        if (fullnameSection.style.display === 'block') {
            if (!firstName || !lastName) {
                frappe.show_alert({message: __('Please enter your first and last name'), indicator: 'red'});
                return;
            }
            //// Neoffice — the mailbox was proven by the code: the account opens with it (auth/code_sign_in.py)
            if (signUpProof) {
                completeSignUp(firstName, lastName);
                return;
            }
            // Create account
            const loginBtn = dialog.querySelector('.btn-submit');
            const originalBtnHtml = loginBtn.innerHTML;
            loginBtn.disabled = true;
            loginBtn.innerHTML = '<div class="lds-ring"><div></div><div></div><div></div><div></div></div>';

            frappe.call({
                method: 'webshop.webshop.auth.api.create_account',
                args: { 
                    email: email, 
                    first_name: firstName, 
                    last_name: lastName 
                },
                callback: function(r) {
                    loginBtn.disabled = false;
                    loginBtn.innerHTML = originalBtnHtml;
                    
                    //// Neoffice — the account is opened and signed in at once (auth/confirmation.py,
                    //// #691 D-9): the page is reloaded signed in, the checkout goes on where it was,
                    //// and the server's notice (translated there: a website page resolves no new
                    //// __() string) is shown once the page is back.
                    if (r.message && r.message.message === 'success' && r.message.signed_in) {
                        try { sessionStorage.setItem('webshop_account_opened', r.message.notice || ''); } catch (e) { /* private mode */ }
                        window.location.reload();
                        return;
                    }
                    if (r.message && r.message.message === 'success') {
                        frappe.show_alert({
                            message: __("Account created successfully! Please check your email to activate your account."),
                            indicator: 'green'
                        });
                        
                        const successOverlay = document.createElement('div');
                        successOverlay.className = 'success-message-overlay';
                        successOverlay.innerHTML = `
                            <div class="success-message-container">
                                <div class="success-icon">
                                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                        <circle cx="12" cy="12" r="10" fill="#48BB78"/>
                                        <path d="M16.5 8.5L10.5 14.5L7.5 11.5" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </div>
                                <h3>${__('Success!')}</h3>
                                <p>${__('Account created successfully! Please check your email to activate your account.')}</p>
                                <button class="btn btn-primary" onclick="window.location.reload()">${__('OK')}</button>
                            </div>
                        `;
                        document.body.appendChild(successOverlay);

                        // Add the style for the success message
                        const successStyles = document.createElement('style');
                        successStyles.textContent = `
                            .success-message-overlay {
                                position: fixed;
                                top: 0;
                                left: 0;
                                right: 0;
                                bottom: 0;
                                background: rgba(0, 0, 0, 0.6);
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                z-index: 1060;
                                opacity: 0;
                                transition: opacity 0.3s ease;
                            }
                            .success-message-overlay.show {
                                opacity: 1;
                            }
                            .success-message-container {
                                background: white;
                                border-radius: 8px;
                                padding: 30px;
                                max-width: 400px;
                                text-align: center;
                                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
                                transform: translateY(20px);
                                opacity: 0;
                                transition: all 0.4s ease;
                            }
                            .success-message-overlay.show .success-message-container {
                                transform: translateY(0);
                                opacity: 1;
                            }
                            .success-icon {
                                margin-bottom: 20px;
                            }
                            .success-icon svg {
                                margin: 0 auto;
                            }
                            .success-message-container h3 {
                                font-size: 24px;
                                margin-bottom: 10px;
                                color: #2D3748;
                            }
                            .success-message-container p {
                                color: #4A5568;
                                margin-bottom: 25px;
                                line-height: 1.5;
                            }
                            .success-message-container .btn-primary {
                                margin-top: 20px;
                            }
                        `;
                        document.head.appendChild(successStyles);

                        // Animate the message's appearance
                        requestAnimationFrame(() => {
                            successOverlay.classList.add('show');
                        });
                    } else {
                        // If the account already exists as a Website User,
                        // automatically switch the dialog to login mode so the
                        // customer can sign in without retyping their email.
                        if (r.message && r.message.reason_code === 'account_exists_website') {
                            frappe.show_alert({
                                message: r.message.reason || __('An account already exists with this email. Please sign in instead.'),
                                indicator: 'orange'
                            });
                            showSection(passwordSection);
                            passwordInput.focus();
                            fullnameSection.style.display = 'none';
                            submitBtn.textContent = __('Sign in');
                        } else {
                            frappe.show_alert({
                                message: (r.message && r.message.reason) || __('An error occurred'),
                                indicator: 'red'
                            });
                        }
                    }
                }
            });
        } else {
            if (!password) {
                frappe.show_alert({message: __('Please enter your password'), indicator: 'red'});
                return;
            }
            // Login
            const loginBtn = dialog.querySelector('.btn-submit');
            const originalBtnHtml = loginBtn.innerHTML;
            loginBtn.disabled = true;
            loginBtn.innerHTML = '<div class="lds-ring"><div></div><div></div><div></div><div></div></div>';

            // Ensure minimum loading time of 500ms
            const startTime = Date.now();
            
            frappe.call({
                type: 'POST',
                method: 'webshop.webshop.auth.api.custom_login',
                args: { 
                    usr: email, 
                    pwd: password
                },
                callback: function(r) {
                    loginBtn.disabled = false;
                    loginBtn.innerHTML = originalBtnHtml;
                    
                    if (r.message && r.message.message === 'success') {
                        frappe.show_alert({
                            message: __('Successful connection!'),
                            indicator: 'green'
                        });
                        setTimeout(() => {
                            closeDialog();
                            location.reload();
                        }, 500);
                    } else {
                        frappe.show_alert({
                            message: r.message.reason || __('An error occurred'),
                            indicator: 'red'
                        });
                    }
                },
                statusCode: {
                    200: function() {
                        const elapsedTime = Date.now() - startTime;
                        const remainingTime = Math.max(0, 500 - elapsedTime);
                        
                        setTimeout(() => {
                            loginBtn.disabled = false;
                            loginBtn.innerHTML = originalBtnHtml;
                            
                            frappe.show_alert({
                                message: __('Successful connection!'),
                                indicator: 'green'
                            });
                            setTimeout(() => {
                                closeDialog();
                                location.reload();
                            }, 500);
                        }, remainingTime);
                    },
                    401: function() {
                        const elapsedTime = Date.now() - startTime;
                        const remainingTime = Math.max(0, 500 - elapsedTime);
                        
                        setTimeout(() => {
                            loginBtn.disabled = false;
                            loginBtn.innerHTML = originalBtnHtml;
                            
                            // Shake password field
                            const passwordField = dialog.querySelector('.password-field');
                            passwordField.classList.add('shake');
                            // Remove class after animation
                            setTimeout(() => {
                                passwordField.classList.remove('shake');
                            }, 500);
                            // Display error message
                            frappe.show_alert({
                                message: __('Incorrect password. Please try again.'),
                                indicator: 'red'
                            });

                            // Focus on password field
                            passwordInput.focus();
                        }, remainingTime);
                    },
                    403: function() {
                        const elapsedTime = Date.now() - startTime;
                        const remainingTime = Math.max(0, 500 - elapsedTime);
                        
                        setTimeout(() => {
                            loginBtn.disabled = false;
                            loginBtn.innerHTML = originalBtnHtml;
                            
                            // Shake password field
                            const passwordField = dialog.querySelector('.password-field');
                            passwordField.classList.add('shake');
                            // Remove class after animation
                            setTimeout(() => {
                                passwordField.classList.remove('shake');
                            }, 500);
                            // Display error message
                            frappe.show_alert({
                                message: __('Incorrect email or password. Please try again.'),
                                indicator: 'red'
                            });

                            // Focus on password field
                            passwordInput.focus();
                        }, remainingTime);
                    }
                }
            });
        }
    });

    // Focus on email input
    emailInput.focus();

    // Handle login with email link
    loginWithEmailLink.addEventListener('click', function(e) {
        e.preventDefault();
        const email = emailInput.value.trim();
        
        if (!email) {
            frappe.show_alert({
                message: __('Please enter your email'),
                indicator: 'red'
            });
            return;
        }

        // Add loader to link
        const originalLinkHtml = loginWithEmailLink.innerHTML;
        loginWithEmailLink.disabled = true;
        loginWithEmailLink.innerHTML = '<div class="lds-ring"><div></div><div></div><div></div><div></div></div>';

        frappe.call({
            method: 'frappe.www.login.send_login_link',
            args: { email: email },
            callback: function(r) {
                loginWithEmailLink.disabled = false;
                loginWithEmailLink.innerHTML = originalLinkHtml;

                if (!r.exc) {
                    frappe.show_alert({
                        message: __('An email containing the connection link has been sent to you. Please check your inbox.'),
                        indicator: 'green'
                    });
                    setTimeout(() => {
                        closeDialog();
                        if (window.location.href.includes('/checkout')) {
                            window.location.href = '/cart';
                        } else {
                            location.reload();
                        }
                    }, 1000);
                } else {
                    frappe.show_alert({
                        message: __('An error occurred while sending the login link'),
                        indicator: 'red'
                    });
                }
            }
        });
    });
};

//// Neoffice — the notice of an account opened at once (create_account's answer, above), shown once
//// the reloaded page is signed in (auth/confirmation.py, #691 D-9)
frappe.ready(() => {
    let notice = null;
    try {
        notice = sessionStorage.getItem('webshop_account_opened');
        sessionStorage.removeItem('webshop_account_opened');
    } catch (e) { /* private mode: no notice, the page is signed in all the same */ }
    if (notice && frappe.session && frappe.session.user !== 'Guest') {
        frappe.show_alert({message: notice, indicator: 'green'}, 10);
    }
});
