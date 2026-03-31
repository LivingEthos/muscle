class SCLEApp {
    constructor() {
        this.sessions = [];
        this.currentSession = null;
        this.apiBase = '/api';
        
        this.initElements();
        this.initEventListeners();
        this.loadSessions();
    }
    
    initElements() {
        this.sessionList = document.getElementById('sessionList');
        this.chatMessages = document.getElementById('chatMessages');
        this.taskInput = document.getElementById('taskInput');
        this.sendBtn = document.getElementById('sendBtn');
        this.newChatBtn = document.getElementById('newChatBtn');
        this.streamingIndicator = document.getElementById('streamingIndicator');
        this.settingsPanel = document.getElementById('settingsPanel');
        this.settingsBtn = document.getElementById('settingsBtn');
        this.closeSettings = document.getElementById('closeSettings');
        this.inputForm = document.getElementById('inputForm');
    }
    
    initEventListeners() {
        this.inputForm.addEventListener('submit', (e) => {
            e.preventDefault();
            this.sendTask();
        });
        this.taskInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendTask();
            }
        });
        this.newChatBtn.addEventListener('click', () => this.createNewSession());
        this.settingsBtn.addEventListener('click', () => this.toggleSettings(true));
        this.closeSettings.addEventListener('click', () => this.toggleSettings(false));
        
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.settingsPanel.classList.contains('open')) {
                this.toggleSettings(false);
            }
        });
    }
    
    async sendTask() {
        const task = this.taskInput.value.trim();
        if (!task) return;
        
        this.addMessage('user', this.escapeHtml(task));
        this.taskInput.value = '';
        this.showStreaming(true);
        
        try {
            const response = await fetch(`${this.apiBase}/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    task,
                    max_iterations: parseInt(document.getElementById('maxIterations').value) || 20,
                    budget_mode: document.getElementById('budgetMode').value,
                    budget_tokens: parseInt(document.getElementById('fixedBudget').value) || 100000,
                    eval_mode: document.getElementById('evalMode').value,
                    interactive: document.getElementById('interactiveMode').checked,
                    git: document.getElementById('gitIntegration').checked,
                    output_dir: document.getElementById('outputDir').value || './output',
                    webhook_url: document.getElementById('webhookUrl').value || null
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                const data = await response.json();
                this.handleCompleteResponse(data);
            } else {
                throw new Error('Invalid response format');
            }
        } catch (error) {
            this.addMessage('error', `Error: ${this.escapeHtml(error.message)}`);
        } finally {
            this.showStreaming(false);
        }
    }
    
    handleStreamingResponse(data) {
        const reader = data.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        
        return new Promise((resolve, reject) => {
            const readChunk = () => {
                reader.read().then(({ done, value }) => {
                    if (done) {
                        if (buffer) {
                            try {
                                const event = JSON.parse(buffer);
                                this.addStreamingChunk(event);
                            } catch (e) {
                                // Ignore incomplete JSON
                            }
                        }
                        resolve();
                        return;
                    }
                    
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop();
                    
                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const event = JSON.parse(line.slice(6));
                                this.addStreamingChunk(event);
                            } catch (e) {
                                // Ignore invalid JSON
                            }
                        }
                    }
                    readChunk();
                }).catch(reject);
            };
            readChunk();
        });
    }
    
    addStreamingChunk(event) {
        const lastMsg = this.chatMessages.lastElementChild;
        if (lastMsg && lastMsg.classList.contains('generation')) {
            const contentEl = lastMsg.querySelector('.message-content');
            if (contentEl) {
                contentEl.appendChild(document.createTextNode(event.text || ''));
            }
        } else {
            this.addMessage('generation', event.text || '', true);
        }
    }
    
    handleCompleteResponse(data) {
        if (data.status === 'success') {
            this.addMessage('success', `Session completed successfully!\nIterations: ${data.iterations}\nTokens: ${data.tokens}`, false);
            
            if (data.artifacts && Array.isArray(data.artifacts)) {
                for (const artifact of data.artifacts) {
                    this.addCodeBlock(
                        this.escapeHtml(artifact.file_path || 'unknown'),
                        artifact.content || ''
                    );
                }
            }
        } else {
            this.addMessage('error', `Session failed: ${this.escapeHtml(data.error || data.status || 'Unknown error')}`, false);
        }
    }
    
    addMessage(type, content, isStreaming = false) {
        const div = document.createElement('div');
        div.className = `message ${type}`;
        div.setAttribute('role', type === 'error' ? 'alert' : 'article');
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        
        if (type === 'error') {
            contentDiv.textContent = content;
        } else {
            contentDiv.innerHTML = this.formatContent(content);
        }
        
        div.appendChild(contentDiv);
        this.chatMessages.appendChild(div);
        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
    }
    
    addCodeBlock(filename, content) {
        const div = document.createElement('div');
        div.className = 'message generation';
        
        const header = document.createElement('div');
        header.className = 'file-header';
        
        const filenameSpan = document.createElement('span');
        filenameSpan.className = 'file-name';
        filenameSpan.textContent = filename;
        header.appendChild(filenameSpan);
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'code-block';
        contentDiv.textContent = content;
        
        div.appendChild(header);
        div.appendChild(contentDiv);
        this.chatMessages.appendChild(div);
        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    formatContent(text) {
        const escaped = this.escapeHtml(text);
        return escaped.replace(/\n/g, '<br>');
    }
    
    showStreaming(show) {
        this.streamingIndicator.style.display = show ? 'flex' : 'none';
        this.sendBtn.disabled = show;
        this.taskInput.disabled = show;
    }
    
    createNewSession() {
        this.currentSession = {
            id: Date.now(),
            title: 'New Session',
            messages: [],
            created: new Date().toISOString()
        };
        this.sessions.push(this.currentSession);
        this.chatMessages.innerHTML = '';
        this.addMessage('system', 'New session started. Describe the code you want to generate.');
        this.renderSessions();
        this.saveSessions();
    }
    
    renderSessions() {
        this.sessionList.innerHTML = this.sessions.map(s => {
            const title = this.escapeHtml(s.title || 'New Session');
            const date = new Date(s.created).toLocaleDateString();
            return `
                <div class="session-item ${s.id === this.currentSession?.id ? 'active' : ''}" 
                     data-id="${s.id}"
                     role="listitem"
                     tabindex="0"
                     aria-label="Session: ${title}">
                    <div class="title">${title}</div>
                    <div class="meta">${this.escapeHtml(date)}</div>
                </div>
            `;
        }).join('');
        
        this.sessionList.querySelectorAll('.session-item').forEach(item => {
            item.addEventListener('click', () => this.loadSession(parseInt(item.dataset.id, 10)));
            item.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    this.loadSession(parseInt(item.dataset.id, 10));
                }
            });
        });
    }
    
    loadSession(id) {
        const session = this.sessions.find(s => s.id === id);
        if (session) {
            this.currentSession = session;
            this.renderSessions();
        }
    }
    
    loadSessions() {
        try {
            const saved = localStorage.getItem('scle_sessions');
            if (saved) {
                this.sessions = JSON.parse(saved);
            }
        } catch (e) {
            this.sessions = [];
        }
        this.renderSessions();
    }
    
    saveSessions() {
        try {
            localStorage.setItem('scle_sessions', JSON.stringify(this.sessions));
        } catch (e) {
            console.warn('Failed to save sessions:', e);
        }
    }
    
    toggleSettings(open) {
        this.settingsPanel.classList.toggle('open', open);
        this.settingsPanel.hidden = !open;
        if (open) {
            this.settingsPanel.querySelector('input, select, button').focus();
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.scleApp = new SCLEApp();
});