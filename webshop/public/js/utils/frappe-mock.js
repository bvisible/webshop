if (!window.frappeMockLoaded && typeof frappe === 'undefined') {
    window.frappeMockLoaded = true;
    window.frappe = {
        provide: function(namespace) {
            var parts = namespace.split('.');
            var parent = window;
            
            for (var i = 0; i < parts.length; i++) {
                var part = parts[i];
                if (!parent[part]) {
                    parent[part] = {};
                }
                parent = parent[part];
            }
            
            return parent;
        },
        session: { user: 'Guest' },
        show_alert: function(opts, seconds = 7, actions = {}) {
            // Map of emojis for different indicators
            let indicator_html_map = {
                orange: "⚠️",
                yellow: "⚠️",
                blue: "ℹ️",
                green: "✅",
                red: "❌",
            };
        
            // Normalize parameters
            if (typeof opts === 'string') {
                opts = { message: opts };
            }
        
            const message = opts.message || '';
            seconds = opts.seconds || seconds;
            
            // Create container if necessary
            if (!document.getElementById('dialog-container')) {
                const container = document.createElement('div');
                container.id = 'dialog-container';
                container.innerHTML = '<div id="alert-container"></div>';
                document.body.appendChild(container);
                
                // Add styles
                if (!document.getElementById('alert-styles')) {
                    const style = document.createElement('style');
                    style.id = 'alert-styles';
                    style.textContent = `
                        #dialog-container {
                            position: fixed;
                            top: 0;
                            right: 0;
                            z-index: 1050;
                            padding: 10px;
                            width: 300px;
                        }
                        #alert-container {
                            display: flex;
                            flex-direction: column;
                            gap: 10px;
                        }
                        .alert.desk-alert {
                            background: white;
                            border-radius: 6px;
                            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
                            padding: 12px;
                            position: relative;
                            border-left: 4px solid;
                            margin-bottom: 10px;
                            animation: fadeInRight 0.3s ease;
                        }
                        @keyframes fadeInRight {
                            from {
                                opacity: 0;
                                transform: translateX(20px);
                            }
                            to {
                                opacity: 1;
                                transform: translateX(0);
                            }
                        }
                        .alert.out {
                            animation: fadeOutRight 0.3s ease forwards;
                        }
                        @keyframes fadeOutRight {
                            from {
                                opacity: 1;
                                transform: translateX(0);
                            }
                            to {
                                opacity: 0;
                                transform: translateX(20px);
                            }
                        }
                        .alert.blue { border-color: #4287f5; }
                        .alert.green { border-color: #28a745; }
                        .alert.red { border-color: #dc3545; }
                        .alert.yellow, .alert.orange { border-color: #ffc107; }
                        .alert-message-container {
                            width: 100%;
                        }
                        .alert-title-container {
                            display: flex;
                            align-items: center;
                            gap: 10px;
                            margin-bottom: 4px;
                        }
                        .alert-emoji {
                            font-size: 16px;
                        }
                        .alert-message {
                            font-size: 14px;
                            font-weight: 500;
                        }
                        .alert-subtitle {
                            font-size: 12px;
                            color: #666;
                            margin-top: 4px;
                        }
                        .alert-body {
                            margin-top: 8px;
                            padding-top: 8px;
                            border-top: 1px solid #eee;
                            font-size: 12px;
                        }
                        .alert .close {
                            position: absolute;
                            top: 8px;
                            right: 8px;
                            cursor: pointer;
                            font-size: 16px;
                            color: #999;
                        }
                        .alert .close:hover {
                            color: #333;
                        }
                    `;
                    document.head.appendChild(style);
                }
            }
        
            // Determine the indicator
            const indicator = opts.indicator?.toLowerCase() || 'blue';
            const emoji = indicator_html_map[indicator] || indicator_html_map.blue;
            
            // Create alert element
            const div = document.createElement('div');
            div.className = `alert desk-alert ${indicator}`;
            div.setAttribute('role', 'alert');
            div.innerHTML = `
                <div class="alert-message-container">
                    <div class="alert-title-container">
                        <span class="alert-emoji">${emoji}</span>
                        <div class="alert-message">${message}</div>
                    </div>
                    <div class="alert-subtitle">${opts.subtitle || ''}</div>
                </div>
                ${opts.body ? `<div class="alert-body">${opts.body}</div>` : ''}
                <a class="close">×</a>
            `;
            
            // Add to container
            document.getElementById('alert-container').appendChild(div);
            
            // Configure close button
            const closeBtn = div.querySelector('.close');
            closeBtn.addEventListener('click', function() {
                div.classList.add('out');
                setTimeout(() => {
                    if (div.parentNode) {
                        div.parentNode.removeChild(div);
                    }
                }, 300);
                return false;
            });
            
            // Add actions if specified
            if (actions) {
                for (const [key, action] of Object.entries(actions)) {
                    const actionElem = div.querySelector(`[data-action="${key}"]`);
                    if (actionElem) {
                        actionElem.addEventListener('click', action);
                    }
                }
            }
            
            // Auto-close after delay
            if (seconds) {
                setTimeout(() => {
                    if (div.parentNode) {
                        div.classList.add('out');
                        setTimeout(() => {
                            if (div.parentNode) {
                                div.parentNode.removeChild(div);
                            }
                        }, 300);
                    }
                }, seconds * 1000);
            }
            
            return div;
        },
        call: function (opts) {
            // Normalize parameters
            if (typeof arguments[0] === "string") {
                opts = {
                    method: arguments[0],
                    args: arguments[1],
                    callback: arguments[2],
                };
            }
            
            if (!opts) opts = {};
            
            frappe.prepare_call(opts);
            if (opts.freeze) {
                frappe.freeze();
            }
            
            // Create XHR
            const xhr = new XMLHttpRequest();
            xhr.open(opts.type || "POST", opts.url || "/", true);
            xhr.setRequestHeader("Content-Type", "application/json");
            xhr.setRequestHeader("Accept", "application/json");
            xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
            
            if (frappe.csrf_token) {
                xhr.setRequestHeader("X-Frappe-CSRF-Token", frappe.csrf_token);
            }
            
            if (opts.args && opts.args.cmd) {
                xhr.setRequestHeader("X-Frappe-CMD", opts.args.cmd);
            }
            
            // Handle response
            xhr.onload = function() {
                let data = {};
                
                try {
                    data = JSON.parse(xhr.responseText);
                } catch (e) {
                    if (xhr.responseText) {
                        data = { responseText: xhr.responseText };
                    }
                }
                
                // Status handlers
                if (xhr.status === 200) {
                    if (opts.callback) opts.callback(data);
                    if (opts.success) opts.success(data);
                } else if (xhr.status === 404) {
                    if (opts.statusCode && opts.statusCode[404]) {
                        opts.statusCode[404]();
                    } else {
                        frappe.msgprint && frappe.msgprint(__("Not found"));
                    }
                } else if (xhr.status === 403) {
                    if (opts.statusCode && opts.statusCode[403]) {
                        opts.statusCode[403]();
                    } else {
                        frappe.msgprint && frappe.msgprint(__("Not permitted"));
                    }
                } else if (opts.statusCode && opts.statusCode[xhr.status]) {
                    opts.statusCode[xhr.status]();
                }
                
                // Always callback
                frappe.process_response(opts, data);
            };
            
            // Handle errors
            xhr.onerror = function() {
                if (opts.error) opts.error(xhr);
                frappe.process_response(opts, { responseText: xhr.responseText });
            };
            
            // Complete handler
            xhr.onloadend = function() {
                if (opts.freeze) {
                    frappe.unfreeze();
                }
            };
            
            // Prepare data and send
            let data = opts.args || {};
            
            // Convert method to cmd if necessary
            if (opts.method) {
                data.cmd = opts.method;
            }
            
            // Stringify non-string values
            for (const key in data) {
                if (typeof data[key] !== 'string' && data[key] !== null) {
                    data[key] = JSON.stringify(data[key]);
                }
            }
            
            // Send the request
            xhr.send(JSON.stringify(data));
            
            return xhr;
        },
        prepare_call: function (opts) {
            if (!opts) return;
            
            if (opts.btn) {
                const btn = typeof opts.btn === 'string' ? document.querySelector(opts.btn) : opts.btn;
                if (btn) btn.disabled = true;
            }
            
            if (opts.msg) {
                const msg = typeof opts.msg === 'string' ? document.querySelector(opts.msg) : opts.msg;
                if (msg) msg.style.display = 'none';
            }
            
            if (!opts.args) opts.args = {};
            
            // method
            if (opts.method) {
                opts.args.cmd = opts.method;
            }
            
            // Stringify non-string values
            for (const key in opts.args) {
                if (typeof opts.args[key] !== "string" && opts.args[key] !== null) {
                    opts.args[key] = JSON.stringify(opts.args[key]);
                }
            }
        },
        process_response: function (opts, data) {
            if (!opts) return;
            
            if (opts.btn) {
                const btn = typeof opts.btn === 'string' ? document.querySelector(opts.btn) : opts.btn;
                if (btn) btn.disabled = false;
            }
            
            if (data._server_messages) {
                let server_messages = [];
                try {
                    server_messages = JSON.parse(data._server_messages || "[]");
                } catch (e) {
                    server_messages = [data._server_messages];
                }
                
                const messages = server_messages.map((msg) => {
                    try {
                        return JSON.parse(msg);
                    } catch (e) {
                        return msg;
                    }
                }).join("<br>");
                
                if (opts.error_msg) {
                    const errorMsg = typeof opts.error_msg === 'string' ? document.querySelector(opts.error_msg) : opts.error_msg;
                    if (errorMsg) {
                        errorMsg.innerHTML = messages;
                        errorMsg.style.display = 'block';
                    }
                } else if (frappe.msgprint) {
                    frappe.msgprint(messages);
                }
            }
            
            if (data.exc) {
                try {
                    var err = JSON.parse(data.exc);
                    if (Array.isArray(err)) {
                        err = err.join("\n");
                    }
                    console.error ? console.error(err) : console.log(err);
                } catch (e) {
                    console.error(data.exc);
                }
            }
            
            if (opts.msg && data.message) {
                const msg = typeof opts.msg === 'string' ? document.querySelector(opts.msg) : opts.msg;
                if (msg) {
                    msg.innerHTML = data.message;
                    msg.style.display = 'block';
                }
            }
            
            if (opts.always) {
                opts.always(data);
            }
        },
        show_message: function (text, icon) {
            if (!icon) icon = "fa fa-refresh fa-spin";
            
            // Remove existing message if any
            frappe.hide_message = function() {
                const existingMessage = document.querySelector('.message-overlay');
                if (existingMessage) {
                    document.body.removeChild(existingMessage);
                }
            };
            
            frappe.hide_message();
            
            const messageOverlay = document.createElement('div');
            messageOverlay.className = 'message-overlay';
            messageOverlay.innerHTML = `
                <div class="content">
                    <i class="${icon} text-muted"></i><br>
                    ${text}
                </div>
            `;
            document.body.appendChild(messageOverlay);
        },
        // Add hide_message function
        hide_message: function() {
            const existingMessage = document.querySelector('.message-overlay');
            if (existingMessage) {
                document.body.removeChild(existingMessage);
            }
        },
        // Add msgprint as a stub
        msgprint: function(message) {
            if (typeof message === 'object') {
                message = message.message || JSON.stringify(message);
            }
            alert(message);
        }
    };
    
    // Define the global translation function if it doesn't exist
    if (typeof __ === 'undefined') {
        window.__ = function(str, values) {
            if (!values) return str;
            return str.replace(/\{(\d+)\}/g, function(match, number) {
                return typeof values[number] !== 'undefined' ? values[number] : match;
            });
        };
    }
}