frappe.provide('webshop.auth');

webshop.auth.showLoginDialog = function(opts) {
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
    const dialogHTML = `
        <div class="login-dialog-overlay">
            <div class="login-dialog">
                <div class="login-dialog-header">
                    <div class="welcome-header d-flex justify-content-between">
                        <h3><span class="wave-emoji">👋</span> ${__('Hello')} <span class="user-name"></span></h3>
                        ${!forceLogin ? '<button class="close-btn">&times;</button>' : ''}
                    </div>
                </div>
                <p class="welcome-text">${__('Enter your email address to sign in or create an account')}</p>
                <div class="login-dialog-body">
                    <div class="form-group slide-in">
                        <label for="login_email">${__('Email')}</label>
                        <div class="email-field">
                            <input type="email" id="login_email" class="form-control" 
                                placeholder="${__('jane@example.com')}" required>
                            <button class="btn-verify-email">
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M13.75 6.75L19.25 12L13.75 17.25" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                                    <path d="M19 12H4.75" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                            </button>
                            <svg class="field-icon email-icon" width="16" height="16" viewBox="0 0 16 16" fill="none"
                                xmlns="http://www.w3.org/2000/svg">
                                <path d="M2 6.12119V12.0606C2 12.35 2.115 12.6274 2.31967 12.832C2.52433 13.0367 2.80165 13.1517 3.09091 13.1517H12.9091C13.1984 13.1517 13.4757 13.0367 13.6804 12.832C13.885 12.6274 14 12.35 14 12.0606V6.12119M14 6.06058V4.42421C14 4.13488 13.885 3.85741 13.6804 3.65282C13.4757 3.44823 13.1984 3.3333 12.9091 3.3333H3.09091C2.80165 3.3333 2.52433 3.44823 2.31967 3.65282C2.115 3.85741 2 4.13488 2 4.42421V6.06058L8 8.66664L14 6.06058Z" stroke="currentColor" stroke-width="1.5"/>
                            </svg>
                        </div>
                    </div>
                    <div class="form-group password-section slide-in" style="display: none;">
                        <label for="login_password">${__('Password')}</label>
                        <div class="password-field">
                            <input type="password" id="login_password" class="form-control" 
                                placeholder="•••••">
                            <svg class="field-icon password-icon" width="16" height="16" viewBox="0 0 16 16" fill="none"
                                xmlns="http://www.w3.org/2000/svg">
                                <path d="M4.5 7.5V5.5C4.5 4.30653 5.30653 3.5 6.5 3.5H9.5C10.6935 3.5 11.5 4.30653 11.5 5.5V7.5M6.5 9.5L8 11M8 11L9.5 12.5M8 11L9.5 9.5M8 11L6.5 12.5M4 7.5H12C12.5523 7.5 13 7.94772 13 8.5V13.5C13 14.0523 12.5523 14.5 12 14.5H4C3.44772 14.5 3 14.0523 3 13.5V8.5C3 7.94772 3.44772 7.5 4 7.5Z" stroke="currentColor" stroke-width="1.5"/>
                            </svg>
                            <span toggle="#login_password" class="toggle-password text-muted">${__('Show')}</span>
                        </div>
                        <p class="forgot-password-message">
                            <a href="/login#forgot">${__('Forgot Password?')}</a>
                        </p>
                    </div>
                    <div class="form-group fullname-section slide-in" style="display: none;">
                        <div class="form-group">
                            <label for="first_name">${__('First Name')}</label>
                            <input type="text" id="first_name" class="form-control" required>
                        </div>
                        <div class="form-group">
                            <label for="last_name">${__('Last Name')}</label>
                            <input type="text" id="last_name" class="form-control" required>
                        </div>
                    </div>
                </div>
                <div class="login-dialog-footer slide-in" style="display: none;">
                    <button class="btn btn-primary btn-submit">${__('Continue')}</button>
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
    const overlay = dialog.querySelector('.login-dialog-overlay');
    if (!forceLogin && overlay) {
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) {
                closeDialog();
            }
        });
    }

    // Toggle password visibility
    if (togglePassword && passwordInput) {
        togglePassword.addEventListener('click', function() {
            const type = passwordInput.type === 'password' ? 'text' : 'password';
            passwordInput.type = type;
            togglePassword.textContent = type === 'password' ? __('Show') : __('Hide');
        });
    }

    // Show section with animation
    function showSection(section) {
        section.style.display = 'block';
        requestAnimationFrame(() => {
            section.classList.add('show');
        });
    }

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

                    if (r.message && r.message.message === 'success') {
                        frappe.show_alert({
                            message: __("Account created successfully! Please check your email to activate your account."),
                            indicator: 'green'
                        });
                        
                        // Use msgprint instead of confirm for single OK button
                        frappe.msgprint({
                            title: __('Success'),
                            message: __('Account created successfully! Please check your email to activate your account.'),
                            primary_action: {
                                label: __('OK'),
                                action: function() {
                                    if (opts.callback) opts.callback(r.message);
                                    setTimeout(function() {
                                        window.location.href = '/all-products';
                                    }, 100);
                                }
                            }
                        });
                    } else {
                        frappe.show_alert({
                            message: r.message.reason || __('An error occurred'),
                            indicator: 'red'
                        });
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
