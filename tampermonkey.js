// ==UserScript==
// @name         DeepSeek Assistant Bridge
// @namespace    http://tampermonkey.net/
// @version      7.6
// @description  Bridge between DeepSeek web and local assistant
// @author       rwapppw
// @match        https://chat.deepseek.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_notification
// @run-at       document-idle
// ==/UserScript==

(function() {
    'use strict';

    const LOCAL_API = 'http://127.0.0.1:5000';
    const WAIT_TIME = 3500;

    let lastUserMessage = '';
    let lastReqId = null;
    let isProcessing = false;
    let isBotResponding = false;
    let responseEndTimer = null;
    let currentBotText = '';
    let lastChangeTime = 0;
    let interruptFlag = false;
    let lastStage = 'idle';

    function sendStage(stage) {
        if (stage === lastStage) return;
        lastStage = stage;
        GM_xmlhttpRequest({
            method: 'POST',
            url: LOCAL_API + '/api/send_response',
            data: JSON.stringify({ stage: stage }),
            headers: { 'Content-Type': 'application/json' }
        });
    }

    function switchModel(modelType) {
        let btn = document.querySelector(`[data-model-type="${modelType}"]`);
        if (btn) {
            if (btn.getAttribute('aria-checked') !== 'true') {
                btn.click();
                return true;
            }
            return true;
        }
        const labels = document.querySelectorAll('._321831d');
        const targetName = modelType.charAt(0).toUpperCase() + modelType.slice(1);
        for (const label of labels) {
            if (label.textContent.trim() === targetName) {
                const parent = label.closest('[role="radio"]');
                if (parent) {
                    if (parent.getAttribute('aria-checked') !== 'true') {
                        parent.click();
                        return true;
                    }
                    return true;
                }
            }
        }
        return false;
    }

    function toggleDeepThink(state) {
        const buttons = document.querySelectorAll('.ds-toggle-button');
        for (const btn of buttons) {
            const span = btn.querySelector('span._6dbc175');
            if (span && span.textContent.trim() === 'DeepThink') {
                const isPressed = btn.getAttribute('aria-pressed') === 'true';
                const targetState = (state === 'on');
                if (isPressed !== targetState) {
                    btn.click();
                    return true;
                }
                return true;
            }
        }
        return false;
    }

    function restartPage() {
        // Переход на главную страницу DeepSeek, а не просто перезагрузка
        window.location.href = 'https://chat.deepseek.com';
        return true;
    }

    function sendPromptToDeepSeek(prompt, reqId) {
        if (isProcessing) return;
        isProcessing = true;
        interruptFlag = false;
        sendStage('loading');

        const inputField = document.querySelector('textarea[placeholder="Message DeepSeek"]');
        if (!inputField) {
            isProcessing = false;
            return;
        }

        inputField.focus();
        inputField.select();
        document.execCommand('delete', false, null);
        document.execCommand('insertText', false, prompt);

        setTimeout(() => {
            const sendButton = document.querySelector('button[type="submit"], button[aria-label="Send"]');
            if (sendButton && !sendButton.disabled) {
                sendButton.click();
            } else {
                const enterEvent = new KeyboardEvent('keydown', {
                    key: 'Enter',
                    code: 'Enter',
                    bubbles: true,
                    cancelable: true
                });
                inputField.dispatchEvent(enterEvent);
            }

            sendStage('thinking');
            currentBotText = '';
            lastChangeTime = Date.now();
            isBotResponding = true;
            lastReqId = reqId;
            checkTextStopped(reqId);

            setTimeout(() => { isProcessing = false; }, 2000);
        }, 300);
    }

    function checkTextStopped(reqId) {
        if (responseEndTimer) clearTimeout(responseEndTimer);

        responseEndTimer = setTimeout(() => {
            if (interruptFlag) {
                isBotResponding = false;
                interruptFlag = false;
                sendStage('idle');
                return;
            }

            const timeSinceLastChange = Date.now() - lastChangeTime;
            if (timeSinceLastChange >= WAIT_TIME && currentBotText.length > 10) {
                sendStage('texting');
                sendFinalResponse(currentBotText, reqId);
                isBotResponding = false;
                setTimeout(() => sendStage('idle'), 500);
            } else {
                checkTextStopped(reqId);
            }
        }, 1000);
    }

    function sendFinalResponse(text, reqId) {
        GM_xmlhttpRequest({
            method: 'POST',
            url: LOCAL_API + '/api/send_response',
            data: JSON.stringify({ id: reqId, response: text }),
            headers: { 'Content-Type': 'application/json' },
            onload: () => {},
            onerror: () => {}
        });
    }

    function getPendingRequest() {
        GM_xmlhttpRequest({
            method: 'GET',
            url: LOCAL_API + '/api/get_pending',
            onload: function(response) {
                try {
                    const data = JSON.parse(response.responseText);
                    if (data.type === 'ping') return;
                    if (data.type === 'prompt') {
                        sendPromptToDeepSeek(data.prompt, data.id);
                    } else if (data.type === 'model') {
                        switchModel(data.model);
                    } else if (data.type === 'deepthink') {
                        toggleDeepThink(data.state);
                    } else if (data.type === 'restart') {
                        restartPage();
                    } else if (data.type === 'interrupt') {
                        interruptFlag = true;
                        isBotResponding = false;
                        sendStage('idle');
                    }
                } catch (e) {
                    console.error('Error parsing response:', e);
                }
            },
            onerror: () => {}
        });
    }

    function observeMessages() {
        const observer = new MutationObserver(() => {
            const botMessages = document.querySelectorAll('.ds-markdown');
            if (botMessages.length > 0) {
                const lastMsg = botMessages[botMessages.length - 1];
                let text = lastMsg.textContent.trim();
                if (text && text.length > 5 && !text.match(/^The user wants|^Let me|^I need|^However|^Actually/)) {
                    if (text !== currentBotText) {
                        currentBotText = text;
                        lastChangeTime = Date.now();
                    }
                }
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    function init() {
        observeMessages();
        setInterval(getPendingRequest, 3000);
        GM_notification({ text: 'DeepSeek Bridge loaded', timeout: 1000 });
    }

    if (document.readyState === 'complete') {
        setTimeout(init, 3000);
    } else {
        window.addEventListener('load', () => setTimeout(init, 3000));
    }
})();