function getApiKey() {
        var key = localStorage.getItem('api_key') || localStorage.getItem('admin_api_key') || '';
        if (!key) {
            key = 'sk-webchat-default';
            localStorage.setItem('admin_api_key', key);
        }
        return key;
    }
    const BASE_URL = location.protocol + "//" + location.host;
    
    // 立即获取有效API Key
    fetch('/admin/current-key', {credentials: 'same-origin'}).then(function(r) {
        if (r.ok) return r.json();
    }).then(function(data) {
        if (data && data.api_key) {
            localStorage.setItem('admin_api_key', data.api_key);
        }
        loadModels();
        updateTokenBadge();
        setInterval(updateTokenBadge, 30000);
    });

    // ===== Theme System =====
    (function() {
        var saved = localStorage.getItem('theme');
        var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        var isDark = saved ? saved === 'dark' : prefersDark;
        if (isDark) document.documentElement.setAttribute('data-theme', 'dark');
        document.addEventListener('DOMContentLoaded', function() {
            syncThemeInputs();
            updateThemeButton();
        });
    })();

    function updateThemeButton() {
        var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        var btn = document.getElementById('themeToggle');
        if (!btn) return;
        btn.innerHTML = isDark ? '&#9728;&#65039; <span>浅色模式</span>' : '&#127769; <span>深色模式</span>';
    }

    function toggleTheme() {
        var html = document.documentElement;
        var isDark = html.getAttribute('data-theme') === 'dark';
        if (isDark) {
            html.removeAttribute('data-theme');
            localStorage.setItem('theme', 'light');
        } else {
            html.setAttribute('data-theme', 'dark');
            localStorage.setItem('theme', 'dark');
        }
        updateThemeButton();
        syncThemeInputs();
    }

    function syncThemeInputs() {
        var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        var themeCard = document.querySelector('.config-card');
        if (!themeCard) return;
        themeCard.style.background = 'var(--surface)';
        themeCard.querySelectorAll('input, textarea').forEach(function(el) {
            el.style.background = 'var(--input-bg)';
        });
        var chatHeader = document.querySelector('.chat-header');
        var chatInputArea = document.querySelector('.chat-input-area');
        if (chatHeader) chatHeader.style.background = 'var(--surface)';
        if (chatInputArea) chatInputArea.style.background = 'var(--surface)';
        var codeBlocks = document.querySelectorAll('.rust-code, .msg.assistant pre');
        codeBlocks.forEach(function(el) {
            el.style.background = isDark ? 'var(--code-bg)' : 'var(--bg)';
        });
    }

    // ===== Tab switching =====
function switchTab(name) {
document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
document.getElementById('tab-' + name).classList.add('active');
var items = document.querySelectorAll('.nav-item');
var map = {chat:0, console:1, stats:2, users:3, config:4};
if (map[name] !== undefined) items[map[name]].classList.add('active');
if (name === 'console') loadConsoleData();
if (name === 'stats') loadStatsData();
if (name === 'users') loadUsersList();
}

    // ===== Simple Markdown Renderer =====
function proxyImgUrl(url) {
  if (url && url.match(/^http:\/\//) && location.protocol === 'https:') {
    return '/proxy_image?url=' + encodeURIComponent(url);
  }
  return url;
}
function renderMd(text) {
  if (!text) return '';
  // Extract images BEFORE escaping to preserve URLs
  var imgMap = [];
  var s = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, function(m, alt, url) {
    var idx = imgMap.length;
    imgMap.push({alt: alt || 'image', url: url, proxyUrl: proxyImgUrl(url)});
    return '\u0000IMG' + idx + '\u0000';
  });
  // Escape HTML
  s = s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  // Code blocks
  s = s.replace(/```([\s\S]*?)```/g, function(m, code) {
    return '<pre><code>' + code.replace(/^\n/,'') + '</code></pre>';
  });
  // Inline code
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Bold
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // Italic
  s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
  // Restore images as HTML
  s = s.replace(/\u0000IMG(\d+)\u0000/g, function(m, idx) {
    var img = imgMap[parseInt(idx)];
    return '<div class=\"ai-img-wrap\">'
      + '<img class=\"ai-img\" src=\"' + img.proxyUrl + '\" alt=\"' + img.alt + '\" onclick=\"openImgLightbox(this.src)\" />'
      + '<div class=\"ai-img-hint\" onclick=\"openImgLightbox(this.previousElementSibling.src)\">\u70b9\u51fb\u67e5\u770b\u8be6\u7ec6\u56fe\u7247</div>'
      + '</div>';
  });
  // Unordered list
  s = s.replace(/^[\s]*[-*]\s+(.+)$/gm, '<li>$1</li>');
  s = s.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');
  // Ordered list
  s = s.replace(/^[\s]*\d+\.\s+(.+)$/gm, '<li>$1</li>');
  // Line breaks
  s = s.replace(/\n/g, '<br>');
  // Clean up double <br> inside pre
  s = s.replace(/<pre><code>(.*?)<\/code><\/pre>/gs, function(m, c) {
    return '<pre><code>' + c.replace(/<br>/g, '\n') + '</code></pre>';
  });
  return s;
}

    function timeStr() {
        var d = new Date();
        return d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0') + ':' + d.getSeconds().toString().padStart(2,'0');
    }

    // ===== Chat =====
    var chatHistory = [];
    var attachedImages = []; // [{base64, mime, name}]
    var isSending = false;

    // Load models into selector
async function loadModels() {
        try {
        var resp = await fetch('/v1/models', {headers:{'Authorization':'Bearer '+getApiKey()}});
        var data = await resp.json();
        var sel = document.getElementById('modelSelect');
        sel.innerHTML = '';
        var geminiGroup = document.createElement('optgroup');
        geminiGroup.label = 'Gemini';
        var proxyGroup = document.createElement('optgroup');
        proxyGroup.label = '\u82f3\u4f1f\u8fbe / \u4ee3\u7406';
        (data.data || []).forEach(function(m) {
            var opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.id;
            if (m.id.startsWith('\u82f3\u4f1f\u8fbe/')) {
                proxyGroup.appendChild(opt);
} else {
                geminiGroup.appendChild(opt);
            }
        });
        if (geminiGroup.children.length > 0) sel.appendChild(geminiGroup);
        if (proxyGroup.children.length > 0) sel.appendChild(proxyGroup);
            return data.data || [];
        } catch(e) { console.error(e); return []; }
    }

    function handleFiles(files) {
        for (var i = 0; i < files.length; i++) {
            (function(file) {
                if (!file.type.startsWith('image/')) return;
                var reader = new FileReader();
                reader.onload = function(e) {
                    var base64 = e.target.result;
                    attachedImages.push({base64: base64, mime: file.type, name: file.name});
                    renderPreviews();
                };
                reader.readAsDataURL(file);
            })(files[i]);
        }
        document.getElementById('fileInput').value = '';
    }

    function renderPreviews() {
        var area = document.getElementById('imgPreview');
        area.innerHTML = '';
        attachedImages.forEach(function(img, idx) {
            var div = document.createElement('div');
            div.className = 'img-preview-item';
            div.innerHTML = '<img src="' + img.base64 + '" alt="preview"><button class="remove-img" onclick="removeImg(' + idx + ')">&#215;</button>';
            area.appendChild(div);
        });
    }

    function removeImg(idx) {
        attachedImages.splice(idx, 1);
        renderPreviews();
    }

function addMessage(role, content, extra) {
  var container = document.getElementById('chatMessages');
  var div = document.createElement('div');
  div.className = 'msg ' + role;
  if (role === 'assistant') {
    div.setAttribute('data-time', timeStr());
    div.innerHTML = renderMd(content);
  } else if (role === 'thinking') {
    div.textContent = content;
  } else {
    var html = '';
    if (extra && extra.images && extra.images.length > 0) {
      html += '<div style="margin-bottom:8px;">';
      extra.images.forEach(function(src) {
        html += '<img src="' + src + '" style="max-width:80px;max-height:80px;border-radius:6px;margin-right:4px;">';
      });
      html += '</div>';
    }
    html += text2html(content) + '<span class="msg-time">' + timeStr() + '</span>';
    html += '<div class="msg-actions">';
    html += '<button onclick="copyMsg(this)">\u590d\u5236</button>';
    html += '<button onclick="editMsg(this)">\u7f16\u8f91</button>';
    html += '</div>';
    div.innerHTML = html;
  }
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function updateAssistantDiv(div, replyContent, thinkingContent, isThinkingActive) {
  var html = '';
  if (thinkingContent) {
    html += '<div class="thinking-block">';
    var toggleClass = isThinkingActive ? 'thinking-toggle' : 'thinking-toggle collapsed';
    var contentClass = isThinkingActive ? 'thinking-content' : 'thinking-content collapsed';
    html += '<div class="' + toggleClass + '" onclick="this.classList.toggle(&quot;collapsed&quot;);this.nextElementSibling.classList.toggle(&quot;collapsed&quot;);">';
    html += '<span class="arrow"></span> \u601d\u8003\u8fc7\u7a0b</div>';
    html += '<div class="' + contentClass + '">' + renderMd(thinkingContent) + '</div>';
    html += '</div>';
  }
  html += renderMd(replyContent);
  if (isThinkingActive || !replyContent) {
    html += '<span class="inline-spinner"></span>';
  } else {
    html += '<span class="msg-time">' + div.getAttribute('data-time') + '</span>';
  }
  div.innerHTML = html;
  var tc = div.querySelector('.thinking-content');
  if (tc) tc.scrollTop = tc.scrollHeight;
  div.parentElement.scrollTop = div.parentElement.scrollHeight;
}

    function text2html(t) {
    return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
    }

// ===== Prompt Management =====
var userPrompts = [];
var activePromptId = null;

async function loadPromptList() {
try {
var pResp = await fetch('/admin/prompts/prompt', {credentials:'same-origin'});
var pData = await pResp.json();
userPrompts = pData.data || [];

var pSel = document.getElementById('promptSelect');
pSel.innerHTML = '<option value="">(none)</option>';
userPrompts.forEach(function(p) {
var opt = document.createElement('option');
opt.value = p.id;
opt.textContent = p.title || '(untitled)';
if (p.is_active) opt.selected = true;
pSel.appendChild(opt);
});
activePromptId = (userPrompts.find(function(p){return p.is_active;}) || {}).id || null;
} catch(e) { console.error('loadPromptList', e); }
}

function onPromptChange() {
var val = document.getElementById('promptSelect').value;
var id = val ? parseInt(val) : 0;
fetch('/admin/prompts/prompt/' + id + '/activate', {method:'POST', credentials:'same-origin'}).catch(function(){});
activePromptId = id || null;
}

function openPromptEditor(ptype) {
var existing = userPrompts;
var html = '<div class="prompt-editor-modal" id="promptEditorModal" onclick="if(event.target===this)this.remove()">';
html += '<div class="modal-box">';
html += '<h3>System Prompt \u7ba1\u7406</h3>';
html += '<div style="margin-bottom:12px;">';
existing.forEach(function(p) {
html += '<div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border);">';
html += '<span style="flex:1;font-size:13px;cursor:pointer;' + (p.is_active?'color:var(--blue);font-weight:600;':'') + '" data-prompt-type="prompt" data-prompt-id="' + p.id + '" onclick="selectPromptItem(this.dataset.promptType,parseInt(this.dataset.promptId))">' + (p.title||'(untitled)') + '</span>';
html += '<button style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:16px;" data-prompt-type="prompt" data-prompt-id="' + p.id + '" onclick="deletePromptItem(this.dataset.promptType,parseInt(this.dataset.promptId))">&#128465;</button>';
html += '</div>';
});
html += '</div>';
html += '<hr style="border:none;border-top:1px solid var(--border);margin:16px 0;">';
html += '<input id="promptEditorTitle" placeholder="\u6807\u9898" />';
html += '<textarea id="promptEditorContent" placeholder="System prompt \u5185\u5bb9..."></textarea>';
html += '<div class="modal-btns">';
html += '<button class="btn-secondary" onclick="document.getElementById(&quot;promptEditorModal&quot;).remove()">\u53d6\u6d88</button>';
html += '<button class="btn-primary" data-prompt-type="prompt" onclick="savePromptItem(this.dataset.promptType)">\u4fdd\u5b58</button>';
html += '</div></div></div>';
document.body.insertAdjacentHTML('beforeend', html);
}

async function savePromptItem(ptype) {
var title = document.getElementById('promptEditorTitle').value.trim();
var content = document.getElementById('promptEditorContent').value.trim();
if (!content) return;
var resp = await fetch('/admin/prompts/' + ptype, {
method: 'POST', credentials: 'same-origin',
headers: {'Content-Type': 'application/json'},
body: JSON.stringify({title: title, content: content})
});
var data = await resp.json();
if (data.success) {
document.getElementById('promptEditorModal').remove();
loadPromptList();
}
}

async function selectPromptItem(ptype, id) {
var item = userPrompts.find(function(p){return p.id === id;});
if (!item) return;
document.getElementById('promptEditorTitle').value = item.title;
document.getElementById('promptEditorContent').value = item.content;
document.getElementById('promptSelect').value = id.toString();
fetch('/admin/prompts/prompt/' + id + '/activate', {method:'POST', credentials:'same-origin'}).catch(function(){});
activePromptId = id;
}

async function deletePromptItem(ptype, id) {
await fetch('/admin/prompts/' + ptype + '/' + id, {method:'DELETE', credentials:'same-origin'});
document.getElementById('promptEditorModal').remove();
loadPromptList();
}

function getActivePromptContent() {
var p = userPrompts.find(function(x){return x.id === activePromptId;});
return (p && p.content) || '';
}

loadPromptList();

    loadPromptList();

    async function sendMessage() {
        if (isSending) return;
        var input = document.getElementById('chatInput');
        var text = input.value.trim();
        if (!text && attachedImages.length === 0) return;

        isSending = true;
        document.getElementById('sendBtn').disabled = true;

        // Build user message content
        var content;
        var imgSrcs = [];
        if (attachedImages.length > 0) {
            content = [];
            if (text) content.push({type: 'text', text: text});
            attachedImages.forEach(function(img) {
                imgSrcs.push(img.base64);
                content.push({type: 'image_url', image_url: {url: img.base64}});
            });
        } else {
            content = text;
        }

        // Show user message
        addMessage('user', text, {images: imgSrcs});
        input.value = '';
        input.style.height = 'auto';
        attachedImages = [];
        renderPreviews();

        // Add to history
        chatHistory.push({role: 'user', content: content});

        // Inject active prompt as system message
        var systemPrompt = getActivePromptContent();
        var messagesToSend = chatHistory.slice();
        if (systemPrompt) {
            messagesToSend = [{role: 'system', content: systemPrompt}].concat(messagesToSend);
        }

// Show assistant bubble with spinner
var replyDiv = addMessage('assistant', '');
replyDiv.innerHTML = '<span class="inline-spinner"></span>';

try {
            var model = document.getElementById('modelSelect').value || 'gemini-3.0-flash';
            var resp = await fetch('/v1/chat/completions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + getApiKey()
                },
                    body: JSON.stringify({
                    model: model,
                    messages: messagesToSend,
                    stream: true
                })
            });
            
        if (!resp.ok) {
            var errText;
            try { var errJson = await resp.json(); errText = errJson.detail || errJson.error || JSON.stringify(errJson); }
catch(_) { errText = await resp.text().catch(function(){return '\u8bf7\u6c42\u5931\u8d25 (HTTP ' + resp.status + ')'}); }
replyDiv.remove();
addMessage('assistant', '\u9519\u8bef: ' + errText);
isSending = false;
document.getElementById('sendBtn').disabled = false;
return;
}

var replyContent = '';
var thinkingContent = '';
var thinkingDone = false;
var _inThinkTag = -1;

        var reader = resp.body.getReader();
        var decoder = new TextDecoder();

        while (true) {
            var result = await reader.read();
            if (result.done) break;
            var chunk = decoder.decode(result.value);
            var lines = chunk.split(String.fromCharCode(10));
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim();
                if (line.startsWith('data: ')) {
                    var dataStr = line.substring(6);
                    if (dataStr === '[DONE]') continue;
                    try {
                        var data = JSON.parse(dataStr);
                        var delta = data.choices[0].delta;
                    if (delta) {
                        // reasoning_content / reasoning: thinking
                        if (delta.reasoning_content) {
                            thinkingContent += delta.reasoning_content;
                            updateAssistantDiv(replyDiv, replyContent, thinkingContent, true);
                        }
                        if (delta.reasoning) {
                            thinkingContent += delta.reasoning;
                            updateAssistantDiv(replyDiv, replyContent, thinkingContent, true);
                        }
// content: check for inline thinking tags
if (delta.content) {
var c = delta.content;
var thinkPairs = [
{open: '<thinking>', close: '</thinking>'},
{open: '<think>', close: '</think>'},
{open: '<reasoning>', close: '</reasoning>'},
{open: '<reason>', close: '</reason>'},
{open: '<reflect>', close: '</reflect>'},
{open: '<reflection>', close: '</reflection>'},
{open: '<thought>', close: '</thought>'}
];
var matched = false;
for (var ti = 0; ti < thinkPairs.length; ti++) {
var pair = thinkPairs[ti];
var hasOpen = c.indexOf(pair.open) > -1;
var hasClose = c.indexOf(pair.close) > -1;
if (hasOpen || _inThinkTag === ti) {
_inThinkTag = ti;
matched = true;
if (hasOpen) {
c = c.split(pair.open)[1] || '';
}
if (hasClose) {
var beforeClose = c.split(pair.close)[0] || '';
var afterClose = c.substring(c.indexOf(pair.close) + pair.close.length);
thinkingContent += beforeClose;
if (afterClose) replyContent += afterClose;
thinkingDone = true;
_inThinkTag = -1;
} else {
thinkingContent += c;
c = '';
}
break;
}
}
if (!matched && c) {
if (thinkingContent && !thinkingDone) {
thinkingDone = true;
_inThinkTag = -1;
}
replyContent += c;
}
updateAssistantDiv(replyDiv, replyContent, thinkingContent, !thinkingDone);
}
                        }
                    } catch(e) {}
                }
            }
        }

// final update with time (thinking done, collapse)
updateAssistantDiv(replyDiv, replyContent, thinkingContent, false);

chatHistory.push({role: 'assistant', content: replyContent});

} catch(e) {
addMessage('assistant', '\u8bf7\u6c42\u5931\u8d25: ' + e.message);
    }

        isSending = false;
        document.getElementById('sendBtn').disabled = false;
    }

    // Auto-resize textarea
    document.getElementById('chatInput').addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });
    document.getElementById('chatInput').addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // ===== Token Status =====
    async function updateTokenBadge() {
        var badges = [document.getElementById('tokenBadge'), document.getElementById('cfgTokenBadge')];
        try {
            var resp = await fetch('/v1/token/status', {headers:{'Authorization':'Bearer '+getApiKey()}});
            var data = await resp.json();
            badges.forEach(function(b) {
                if (!b) return;
                if (data.has_snlm0e) {
                    b.className = 'token-badge valid';
                    b.textContent = 'Token 有效 | 已刷新 ' + data.total_refresh_count + ' 次';
                } else {
                    b.className = 'token-badge invalid';
                    b.textContent = 'Token 已失效';
                }
            });
        } catch(e) {
            badges.forEach(function(b) {
                if (!b) return;
                b.className = 'token-badge invalid';
                b.textContent = '无法获取状态';
            });
        }
    }

// ===== Console =====
var consoleTimer = null;
var lastConsoleSnapshot = null;

function refreshTokenNow() {
fetch('/v1/token/refresh', {
method: 'POST',
headers: {'Authorization': 'Bearer ' + getApiKey()}
}).then(function(r) { return r.json(); }).then(function() {
updateTokenBadge();
}).catch(function(err) { console.error(err); });
}

function resetClientNow() {
fetch('/v1/client/reset', {
method: 'POST',
headers: {'Authorization': 'Bearer ' + getApiKey()}
}).then(function(r) { return r.json(); }).then(function() {
loadStatsData();
}).catch(function(err) { console.error(err); });
}

async function loadConsoleData() {
document.getElementById('dispBaseUrl').textContent = BASE_URL + '/v1';
loadApiKeys();
try {
var resp2 = await fetch('/v1/models', {headers:{'Authorization':'Bearer '+getApiKey()}});
if (resp2.ok) {
var mdata = await resp2.json();
var ml = document.getElementById('modelsList');
ml.innerHTML = '';
(mdata.data || []).forEach(function(m) {
var tag = document.createElement('span');
tag.className = 'model-tag';
tag.textContent = m.id;
ml.appendChild(tag);
});
}
} catch(e) { console.error('Models error:', e); }
document.getElementById('rustCode').textContent = '// Cargo.toml 依赖\n// [dependencies]\n// reqwest = { version = "0.12", features = ["json"] }\n// serde = { version = "1", features = ["derive"] }\n// serde_json = "1"\n// tokio = { version = "1", features = ["full"] }\n\nuse serde::{Deserialize, Serialize};\n\n#[derive(Serialize)]\nstruct ChatRequest {\n    model: String,\n    messages: Vec<Message>,\n    stream: bool,\n}\n\n#[derive(Serialize)]\nstruct Message {\n    role: String,\n    content: String,\n}\n\n#[derive(Deserialize)]\nstruct ChatResponse {\n    choices: Vec<Choice>,\n    usage: Usage,\n}\n\n#[derive(Deserialize)]\nstruct Choice {\n    message: ResponseMessage,\n}\n\n#[derive(Deserialize)]\nstruct ResponseMessage {\n    content: String,\n}\n\n#[derive(Deserialize)]\nstruct Usage {\n    prompt_tokens: u32,\n    completion_tokens: u32,\n    total_tokens: u32,\n}\n\n#[tokio::main]\nasync fn main() -> Result<(), Box<dyn std::error::Error>> {\n    let client = reqwest::Client::new();\n\n    let request = ChatRequest {\n        model: "gemini-3.0-flash".to_string(),\n        messages: vec![Message {\n            role: "user".to_string(),\n            content: "你好".to_string(),\n        }],\n        stream: false,\n    };\n\n    let response = client\n        .post("' + BASE_URL + '/v1/chat/completions")\n        .header("Authorization", "Bearer sk-xxxxxxxxx")\n        .json(&request)\n        .send()\n        .await?\n        .json::<ChatResponse>()\n        .await?;\n\n    println!("回复: {}", response.choices[0].message.content);\n    println!("Token 用量: {}", response.usage.total_tokens);\n\n    Ok(())\n}';
try {
var hResp = await fetch('/admin/user-hourly-stats', {credentials:'same-origin'});
if (hResp.ok) {
var hData = await hResp.json();
var hourly = hData.data || [];
console.log('[Console] user-hourly-stats rows:', hourly.length);
drawUserModelBarChart(hourly);
drawUserTokenLineChart(hourly);
} else {
console.error('user-hourly-stats HTTP', hResp.status);
}
} catch(e) { console.error('User hourly stats error:', e); }
if (consoleTimer) clearInterval(consoleTimer);
consoleTimer = setInterval(loadConsoleData, 10000);
}

var CHART_COLORS = ['#4285f4','#ea4335','#fbbc04','#34a853','#ff6d01','#46bdc6','#7b1fa2','#e91e63','#00bcd4','#8bc34a'];

function drawUserModelBarChart(hourlyData) {
  var canvas = document.getElementById('userModelBarChart');
  if (!canvas) return;
  var dpr = window.devicePixelRatio || 1;
  var rect = canvas.parentElement.getBoundingClientRect();
  var W = rect.width - 32; if (W < 100) W = 100;
  var H = parseInt(canvas.getAttribute('data-design-height')) || 200;
  canvas.setAttribute('data-design-height', H);
  canvas.width = W * dpr; canvas.height = H * dpr;
canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
var ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
var now = new Date(); var curHour = now.getHours();
var models = {}; var hours = [];
for (var i = 0; i < 24; i++) { var h = (curHour - 23 + i + 24) % 24; hours.push(h); }
hourlyData.forEach(function(d) { if (!models[d.model]) models[d.model] = {}; models[d.model][d.hour] = d.requests; });
var modelNames = Object.keys(models);
if (modelNames.length === 0) { ctx.clearRect(0,0,W,H); ctx.fillStyle = '#9aa0a6'; ctx.font = '13px sans-serif'; ctx.textAlign = 'center'; ctx.fillText('\u6682\u65e0\u6570\u636e', W/2, H/2); return; }
var maxVal = 0;
for (var hi = 0; hi < 24; hi++) { var total = 0; modelNames.forEach(function(m){ total += (models[m][hours[hi]] || 0); }); if (total > maxVal) maxVal = total; }
if (maxVal === 0) maxVal = 1;
var padL = 50, padR = 10, padT = 10, padB = 55;
var cW = W - padL - padR; var cH = H - padT - padB;
var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
var gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)';
var textColor = isDark ? '#9aa0a6' : '#5f6368';
ctx.clearRect(0, 0, W, H);
ctx.strokeStyle = gridColor; ctx.lineWidth = 1;
for (var g = 0; g <= 4; g++) {
var gy = padT + cH - (cH * g / 4);
ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(padL + cW, gy); ctx.stroke();
ctx.fillStyle = textColor; ctx.font = '11px sans-serif'; ctx.textAlign = 'right';
ctx.fillText(Math.round(maxVal * g / 4), padL - 6, gy + 4);
}
ctx.textAlign = 'center'; ctx.font = '10px sans-serif';
var barW = cW / 24;
for (var xi = 0; xi < 24; xi++) {
if (xi % 3 === 0) ctx.fillText(hours[xi].toString().padStart(2,'0')+':00', padL + barW * xi + barW/2, H - 6);
}
for (var bi = 0; bi < 24; bi++) {
var bottomY = padT + cH;
for (var mi = 0; mi < modelNames.length; mi++) {
var val = models[modelNames[mi]][hours[bi]] || 0;
if (val === 0) continue;
var bH = cH * val / maxVal;
bottomY -= bH;
ctx.fillStyle = CHART_COLORS[mi % CHART_COLORS.length];
ctx.fillRect(padL + barW * bi + 2, bottomY, barW - 4, bH);
}
}
var lx = padL; var ly = H - 30;
modelNames.forEach(function(m, idx) {
ctx.fillStyle = CHART_COLORS[idx % CHART_COLORS.length];
ctx.fillRect(lx, ly, 10, 10);
ctx.fillStyle = textColor; ctx.font = '10px sans-serif'; ctx.textAlign = 'left';
var short = m.length > 15 ? m.substring(0,15)+'...' : m;
ctx.fillText(short, lx + 14, ly + 9);
lx += ctx.measureText(short).width + 24;
if (lx > W - 60) { lx = padL; ly -= 14; }
});
}

function drawUserTokenLineChart(hourlyData) {
  var canvas = document.getElementById('userTokenLineChart');
  if (!canvas) return;
  var dpr = window.devicePixelRatio || 1;
  var rect = canvas.parentElement.getBoundingClientRect();
  var W = rect.width - 32; if (W < 100) W = 100;
  var H = parseInt(canvas.getAttribute('data-design-height')) || 200;
  canvas.setAttribute('data-design-height', H);
  canvas.width = W * dpr; canvas.height = H * dpr;
canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
var ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
var now = new Date(); var curHour = now.getHours();
var labels = []; var values = [];
for (var i = 0; i < 24; i++) {
var h = (curHour - 23 + i + 24) % 24;
labels.push(h.toString().padStart(2, '0') + ':00');
var total = 0;
for (var j = 0; j < hourlyData.length; j++) { if (hourlyData[j].hour === h) total += hourlyData[j].total_tokens; }
values.push(total);
}
if (Math.max.apply(null, values) === 0) { ctx.clearRect(0,0,W,H); ctx.fillStyle = '#9aa0a6'; ctx.font = '13px sans-serif'; ctx.textAlign = 'center'; ctx.fillText('\u6682\u65e0\u6570\u636e', W/2, H/2); return; }
drawLineChart(ctx, W, H, labels, values, '#34a853', '#0d904f');
}

function drawLineChart(ctx, W, H, labels, values, lineColor, fillColor) {
var maxVal = Math.max.apply(null, values); if (maxVal === 0) maxVal = 1;
var padL = 60, padR = 10, padT = 10, padB = 30;
var cW = W - padL - padR; var cH = H - padT - padB;
var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
var gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)';
var textColor = isDark ? '#9aa0a6' : '#5f6368';
ctx.clearRect(0, 0, W, H);
ctx.strokeStyle = gridColor; ctx.lineWidth = 1;
for (var g = 0; g <= 4; g++) { var gy = padT + cH - (cH * g / 4); ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(padL + cW, gy); ctx.stroke(); ctx.fillStyle = textColor; ctx.font = '11px sans-serif'; ctx.textAlign = 'right'; ctx.fillText(formatNum(Math.round(maxVal * g / 4)), padL - 6, gy + 4); }
ctx.textAlign = 'center'; ctx.font = '10px sans-serif';
for (var xi = 0; xi < 24; xi += 3) { var xx = padL + (cW * xi / 23); ctx.fillText(labels[xi], xx, H - 4); }
ctx.beginPath();
for (var li = 0; li < 24; li++) { var lx = padL + (cW * li / 23); var ly = padT + cH - (cH * values[li] / maxVal); if (li === 0) ctx.moveTo(lx, ly); else ctx.lineTo(lx, ly); }
ctx.strokeStyle = lineColor; ctx.lineWidth = 2; ctx.stroke();
ctx.lineTo(padL + cW, padT + cH); ctx.lineTo(padL, padT + cH); ctx.closePath(); ctx.fillStyle = fillColor + '22'; ctx.fill();
for (var di = 0; di < 24; di++) { if (values[di] > 0) { var dx = padL + (cW * di / 23); var dy = padT + cH - (cH * values[di] / maxVal); ctx.beginPath(); ctx.arc(dx, dy, 3, 0, 6.2832); ctx.fillStyle = lineColor; ctx.fill(); } }
}

function formatNum(n) { if (n >= 1000000) return (n/1000000).toFixed(1)+'M'; if (n >= 1000) return (n/1000).toFixed(1)+'K'; return n.toString(); }

// ===== Global Stats =====
var statsTimer = null;
async function loadStatsData() {
try {
var resp = await fetch('/admin/stats', {credentials:'same-origin'});
if (resp.status === 401) { location.href = '/admin/login'; return; }
var s = await resp.json();
lastConsoleSnapshot = s;
document.getElementById('statReqs').textContent = s.total_requests;
document.getElementById('statTokens').textContent = formatNum(s.total_tokens);
document.getElementById('statPrompt').textContent = formatNum(s.total_prompt_tokens);
document.getElementById('statCompletion').textContent = formatNum(s.total_completion_tokens);
document.getElementById('statUptime').textContent = s.uptime;
document.getElementById('statRefresh').textContent = s.token_refresh_count;
document.getElementById('statBackground').textContent = s.background_refresh_enabled ? '\u5f00\u542f' : '\u5173\u95ed';
document.getElementById('statClient').textContent = s.client_active ? '\u5728\u7ebf' : '\u79bb\u7ebf';
document.getElementById('statAutoRefresh').textContent = s.auto_refresh_enabled ? '\u5f00\u542f' : '\u5173\u95ed';
document.getElementById('statBgRefresh').textContent = s.background_refresh_enabled ? '\u5f00\u542f' : '\u5173\u95ed';
document.getElementById('statUpdatedAt').textContent = new Date().toLocaleString();
if (s.today_requests !== undefined) { var el = document.getElementById('statTodayReqs'); if (el) el.textContent = s.today_requests; }
if (s.today_tokens !== undefined) { var el2 = document.getElementById('statTodayTokens'); if (el2) el2.textContent = formatNum(s.today_tokens); }
var chart = document.getElementById('modelUsageChart');
var models = s.requests_by_model || {}; var keys = Object.keys(models);
if (keys.length === 0) {
chart.innerHTML = '<span style="color:var(--muted);font-size:13px;">\u6682\u65e0\u8bf7\u6c42\u6570\u636e</span>';
} else {
var maxVal = Math.max.apply(null, keys.map(function(k){return models[k];}));
chart.innerHTML = '';
keys.sort(function(a, b) { return models[b] - models[a]; });
keys.forEach(function(k, idx) {
var pct = maxVal > 0 ? (models[k] / maxVal * 100) : 0;
var color = CHART_COLORS[idx % CHART_COLORS.length];
var row = document.createElement('div'); row.className = 'model-bar';
row.innerHTML = '<div class="name">' + k + '</div><div class="bar-bg"><div class="bar-fill" style="width:' + pct + '%;background:' + color + '">' + models[k] + '</div></div>';
chart.appendChild(row);
});
document.getElementById('statModelCount').textContent = keys.length;
}
} catch(e) { console.error('Stats error:', e); }
try {
var hResp = await fetch('/admin/hourly-stats', {credentials:'same-origin'});
var hData = await hResp.json();
var hourly = hData.data || [];
drawHourlyChart('hourlyReqsChart', hourly, 'requests', '#1a73e8', '#4285f4');
drawHourlyChart('hourlyTokensChart', hourly, 'total_tokens', '#34a853', '#0d904f');
} catch(e) { console.error('Hourly stats error:', e); }
if (statsTimer) clearInterval(statsTimer);
statsTimer = setInterval(loadStatsData, 10000);
}

function drawHourlyChart(canvasId, hourlyData, field, lineColor, fillColor) {
  var canvas = document.getElementById(canvasId);
  if (!canvas) return;
  var dpr = window.devicePixelRatio || 1;
  var rect = canvas.parentElement.getBoundingClientRect();
  var W = rect.width - 32;
  var H = parseInt(canvas.getAttribute('data-design-height')) || 160;
  canvas.setAttribute('data-design-height', H);
  canvas.width = W * dpr;
canvas.height = H * dpr;
canvas.style.width = W + 'px';
canvas.style.height = H + 'px';
var ctx = canvas.getContext('2d');
ctx.scale(dpr, dpr);

var now = new Date();
var curHour = now.getHours();
var labels = [];
var values = [];
for (var i = 0; i < 24; i++) {
var h = (curHour - 23 + i + 24) % 24;
labels.push(h.toString().padStart(2, '0') + ':00');
var found = null;
for (var j = 0; j < hourlyData.length; j++) {
if (hourlyData[j].hour === h) { found = hourlyData[j]; break; }
}
values.push(found ? found[field] : 0);
}

var maxVal = Math.max.apply(null, values);
if (maxVal === 0) maxVal = 1;
var padL = 50, padR = 10, padT = 10, padB = 30;
var cW = W - padL - padR;
var cH = H - padT - padB;

var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
var gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)';
var textColor = isDark ? '#9aa0a6' : '#5f6368';

ctx.clearRect(0, 0, W, H);

// grid
ctx.strokeStyle = gridColor;
ctx.lineWidth = 1;
for (var g = 0; g <= 4; g++) {
var gy = padT + cH - (cH * g / 4);
ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(padL + cW, gy); ctx.stroke();
ctx.fillStyle = textColor;
ctx.font = '11px sans-serif';
ctx.textAlign = 'right';
ctx.fillText(Math.round(maxVal * g / 4), padL - 6, gy + 4);
}

// x labels
ctx.textAlign = 'center';
ctx.font = '10px sans-serif';
for (var xi = 0; xi < 24; xi += 3) {
var xx = padL + (cW * xi / 23);
ctx.fillText(labels[xi], xx, H - 4);
}

// line + fill
ctx.beginPath();
for (var li = 0; li < 24; li++) {
var lx = padL + (cW * li / 23);
var ly = padT + cH - (cH * values[li] / maxVal);
if (li === 0) ctx.moveTo(lx, ly); else ctx.lineTo(lx, ly);
}
ctx.strokeStyle = lineColor;
ctx.lineWidth = 2;
ctx.stroke();

ctx.lineTo(padL + cW, padT + cH);
ctx.lineTo(padL, padT + cH);
ctx.closePath();
ctx.fillStyle = fillColor + '22';
ctx.fill();

// dots
for (var di = 0; di < 24; di++) {
var dx = padL + (cW * di / 23);
var dy = padT + cH - (cH * values[di] / maxVal);
if (values[di] > 0) {
ctx.beginPath(); ctx.arc(dx, dy, 3, 0, 6.2832);
ctx.fillStyle = lineColor; ctx.fill();
}
}
}

// ===== User Management =====
async function loadUsersList() {
try {
var resp = await fetch('/admin/users', {credentials:'same-origin'});
if (resp.status === 403) { document.getElementById('usersList').innerHTML = '<p style="color:var(--muted);text-align:center;padding:40px;">需要管理员权限</p>'; return; }
var data = await resp.json();
var users = data.data || [];
var container = document.getElementById('usersList');
document.getElementById('userDetail').style.display = 'none';
container.style.display = '';
var html = '';
if (users.length === 0) {
html = '<p style="color:var(--muted);text-align:center;padding:40px;">暂无用户</p>';
} else {
users.forEach(function(u) {
html += '<div class="user-card" onclick="loadUserDetail(' + u.id + ')">';
html += '<div class="user-info">';
html += '<div class="user-name">' + u.username + (u.is_admin ? ' <span style="font-size:11px;background:#e6f4ea;color:#137333;padding:2px 8px;border-radius:10px;margin-left:6px;">管理员</span>' : '') + '</div>';
html += '<div class="user-meta">';
html += '<span>ID: ' + u.id + '</span>';
html += '<span>' + (u.email || '-') + '</span>';
html += '<span>Keys: ' + u.key_count + '</span>';
html += '<span>请求: ' + u.total_requests + '</span>';
html += '<span>Tokens: ' + u.total_tokens + '</span>';
if (u.created_at) html += '<span>注册: ' + u.created_at.substring(0,10) + '</span>';
html += '</div></div>';
html += '<div class="user-actions">';
html += '<button class="api-key-item key-btn" data-user-id="' + u.id + '" onclick="event.stopPropagation();toggleAdmin(' + u.id + ',this)">' + (u.is_admin ? '取消管理员' : '设为管理员') + '</button>';
html += '<button class="api-key-item key-btn delete" onclick="event.stopPropagation();deleteUser(' + u.id + ',this)">&#128465;</button>';
html += '</div></div>';
});
}
container.innerHTML = html;
} catch(e) { console.error('loadUsersList', e); }
}

async function loadUserDetail(userId) {
try {
var resp = await fetch('/admin/users/' + userId, {credentials:'same-origin'});
var data = await resp.json();
var u = data.data;
if (!u) return;
var listEl = document.getElementById('usersList');
var detailEl = document.getElementById('userDetail');
listEl.style.display = 'none';
detailEl.style.display = '';
var html = '<button class="back-btn" onclick="loadUsersList()">&#8592; 返回用户列表</button>';
html += '<div class="user-detail-panel">';
html += '<h3>' + u.username + ' <span style="font-size:14px;color:var(--muted);font-weight:400;">(ID: ' + u.id + ')</span>';
html += u.is_admin ? ' <span style="font-size:11px;background:#e6f4ea;color:#137333;padding:2px 8px;border-radius:10px;">管理员</span>' : '';
html += '</h3>';
html += '<div class="detail-grid">';
html += '<div class="detail-item"><div class="label">邮箱</div><div class="value">' + (u.email || '-') + '</div></div>';
html += '<div class="detail-item"><div class="label">角色</div><div class="value">' + (u.is_admin ? '管理员' : '普通用户') + '</div></div>';
html += '<div class="detail-item"><div class="label">注册时间</div><div class="value">' + (u.created_at || '-') + '</div></div>';
html += '<div class="detail-item"><div class="label">API Keys</div><div class="value">' + (u.api_keys ? u.api_keys.length : 0) + '</div></div>';
html += '<div class="detail-item"><div class="label">总请求数</div><div class="value">' + (u.stats.total_requests || 0) + '</div></div>';
html += '<div class="detail-item"><div class="label">总 Tokens</div><div class="value">' + (u.stats.total_tokens || 0) + '</div></div>';
html += '<div class="detail-item"><div class="label">Prompt Tokens</div><div class="value">' + (u.stats.total_prompt_tokens || 0) + '</div></div>';
html += '<div class="detail-item"><div class="label">Completion Tokens</div><div class="value">' + (u.stats.total_completion_tokens || 0) + '</div></div>';
html += '</div>';

if (u.stats.requests_by_model && Object.keys(u.stats.requests_by_model).length > 0) {
html += '<h4 style="margin:16px 0 8px;font-size:14px;">模型使用分布</h4>';
var models = u.stats.requests_by_model;
var mkeys = Object.keys(models);
mkeys.sort(function(a,b){return models[b]-models[a];});
mkeys.forEach(function(k) {
html += '<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:13px;"><span>' + k + '</span><span style="color:var(--blue);">' + models[k] + '</span></div>';
});
}

if (u.api_keys && u.api_keys.length > 0) {
html += '<h4 style="margin:16px 0 8px;font-size:14px;">API Keys</h4>';
u.api_keys.forEach(function(k) {
html += '<div class="user-key-row">';
html += '<span style="font-family:monospace;color:var(--blue);">' + k.api_key + '</span>';
html += '<span style="color:var(--muted);font-size:11px;">' + (k.note || '') + '</span>';
html += '<span class="api-key-item key-status ' + (k.is_active ? 'active' : 'inactive') + '">' + (k.is_active ? '活跃' : '禁用') + '</span>';
html += '</div>';
});
}

html += '</div>';
detailEl.innerHTML = html;
} catch(e) { console.error('loadUserDetail', e); }
}

async function toggleAdmin(userId, btn) {
try {
var resp = await fetch('/admin/users/' + userId + '/toggle-admin', {method:'POST', credentials:'same-origin'});
var result = await resp.json();
if (result.success) loadUsersList();
} catch(e) { console.error('toggleAdmin', e); }
}

async function deleteUser(userId, btn) {
if (!confirm('确定删除该用户及其所有数据？')) return;
try {
await fetch('/admin/users/' + userId, {method:'DELETE', credentials:'same-origin'});
loadUsersList();
} catch(e) { console.error('deleteUser', e); }
}

// ===== Modal Functions =====
    function openModal(id) {
        var modal = document.getElementById(id);
        if (modal) {
            modal.classList.add('active');
            var input = modal.querySelector('.modal-input');
            if (input) {
                setTimeout(function() { input.focus(); }, 100);
            }
        }
    }
    function closeModal(id) {
        var modal = document.getElementById(id);
        if (modal) modal.classList.remove('active');
    }
    function copyAndCloseKey() {
        var keyText = document.getElementById('created-key-display').textContent;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(keyText).then(function() {
                closeModal('modal-show-key');
            }).catch(function() {
                fallbackCopy(keyText);
            });
        } else {
            fallbackCopy(keyText);
        }
    }
    function fallbackCopy(text) {
        var textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
        } catch(e) {}
        document.body.removeChild(textarea);
        closeModal('modal-show-key');
    }

    // ===== API Key Management =====
    var pendingDeleteKeyId = null;
    async function loadApiKeys() {
        try {
            var resp = await fetch('/admin/api-keys', {credentials:'same-origin'});
            var keys = await resp.json();
            var container = document.getElementById('apiKeysList');
            if (!container) return;
            
            if (keys.length === 0) {
                container.innerHTML = '<span style="color:var(--muted);font-size:13px;">暂无 API Key</span>';
                return;
            }
            
            container.innerHTML = '';
            keys.forEach(function(k) {
                var item = document.createElement('div');
                item.className = 'api-key-item';
                var statusText = k.is_active ? '已启用' : '已禁用';
                var statusClass = k.is_active ? 'active' : 'inactive';
                item.innerHTML = '<div class="key-info"><div class="key-value">' + k.api_key + '</div>' +
                    '<div class="key-note">' + (k.note || '无备注') + ' | ' + k.created_at.substring(0,10) + '</div></div>' +
                    '<span class="key-status ' + statusClass + '">' + statusText + '</span>' +
                    '<div class="key-actions">' +
                    '<button class="key-btn" onclick="toggleApiKey(' + k.id + ')">' + (k.is_active ? '禁用' : '启用') + '</button>' +
                    '<button class="key-btn delete" onclick="confirmDeleteApiKey(' + k.id + ')">删除</button>' +
                    '</div>';
                container.appendChild(item);
            });
        } catch(e) { console.error('Load API keys error:', e); }
    }

    async function showCreateKeyModal() {
        document.getElementById('new-key-note').value = '';
        openModal('modal-create-key');
    }

    document.getElementById('btn-create-key-confirm').addEventListener('click', async function() {
        var btn = this;
        var note = document.getElementById('new-key-note').value;
        btn.disabled = true;
        btn.textContent = '创建中...';
        try {
            var resp = await fetch('/admin/api-keys', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({note: note || ''})
            });
            var result = await resp.json();
            if (result.success && result.data) {
                closeModal('modal-create-key');
                var key = result.data.api_key;
                document.getElementById('created-key-display').textContent = key;
                openModal('modal-show-key');
                loadApiKeys();
            } else {
                var panel = document.querySelector('#modal-create-key .modal-panel');
                panel.classList.add('shake');
                setTimeout(function() { panel.classList.remove('shake'); }, 300);
            }
        } catch(e) {
            var panel = document.querySelector('#modal-create-key .modal-panel');
            panel.classList.add('shake');
            setTimeout(function() { panel.classList.remove('shake'); }, 300);
        } finally {
            btn.disabled = false;
            btn.textContent = '创建';
        }
    });

    document.getElementById('new-key-note').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') document.getElementById('btn-create-key-confirm').click();
    });

    async function toggleApiKey(keyId) {
        try {
            var resp = await fetch('/admin/api-keys/' + keyId + '/toggle', {
                method: 'POST',
                credentials: 'same-origin'
            });
            var result = await resp.json();
            if (result.success) {
                loadApiKeys();
            }
        } catch(e) { console.error('Toggle API key error:', e); }
    }

    function confirmDeleteApiKey(keyId) {
        pendingDeleteKeyId = keyId;
        openModal('modal-delete-key');
    }

    document.getElementById('btn-delete-key-confirm').addEventListener('click', async function() {
        if (!pendingDeleteKeyId) return;
        var btn = this;
        btn.disabled = true;
        btn.textContent = '删除中...';
        try {
            var resp = await fetch('/admin/api-keys/' + pendingDeleteKeyId, {
                method: 'DELETE',
                credentials: 'same-origin'
            });
            var result = await resp.json();
            if (result.success) {
                closeModal('modal-delete-key');
                loadApiKeys();
            }
        } catch(e) { console.error('Delete API key error:', e); }
        finally {
            btn.disabled = false;
            btn.textContent = '确认删除';
            pendingDeleteKeyId = null;
        }
    });

    // Old delete function - kept for compatibility
    async function deleteApiKey(keyId) {
        // Deprecated - use confirmDeleteApiKey instead
    }

    // ===== Config =====
    var configLoaded = false;

    // Cookie field mapping
    var cookieFields = {
        '__Secure-1PSID': 'SECURE_1PSID',
        '__Secure-1PSIDTS': 'SECURE_1PSIDTS',
        'SAPISID': 'SAPISID',
        '__Secure-1PAPISID': 'SECURE_1PAPISID',
        'SID': 'SID',
        'HSID': 'HSID',
        'SSID': 'SSID',
        'APISID': 'APISID'
    };

    function parseCookie(str) {
        var result = {};
        if (!str) return result;
        str.split(';').forEach(function(item) {
            var t = item.trim();
            var eq = t.indexOf('=');
            if (eq > 0) {
                var k = t.substring(0, eq).trim();
                var v = t.substring(eq + 1).trim();
                if (cookieFields[k]) result[cookieFields[k]] = v;
            }
        });
        return result;
    }

    function showParsedFields(parsed) {
        var container = document.getElementById('parsedFields');
        var infoBox = document.getElementById('parsedInfo');
        var names = {
            'SECURE_1PSID': '__Secure-1PSID',
            'SECURE_1PSIDTS': '__Secure-1PSIDTS',
            'SAPISID': 'SAPISID',
            'SID': 'SID',
            'HSID': 'HSID',
            'SSID': 'SSID',
            'APISID': 'APISID'
        };
        var html = '';
        var has = false;
        for (var key in names) {
            if (parsed[key]) {
                has = true;
                var sv = parsed[key].length > 30 ? parsed[key].substring(0,30) + '...' : parsed[key];
                html += '<div class="item">' + names[key] + ': <span>' + sv + '</span></div>';
            }
        }
        if (has) { container.innerHTML = html; infoBox.style.display = 'block'; }
        else { infoBox.style.display = 'none'; }
    }

    function parseModelId(input) {
        try {
            var arr = JSON.parse(input);
            if (Array.isArray(arr) && arr.length > 4 && typeof arr[4] === 'string') return arr[4];
        } catch(e) {
            var match = input.match(/["']([a-f0-9]{16})["']/i);
            if (match) return match[1];
        }
        return null;
    }

    function fillModelId(type, id) {
        var map = {flash:'MODEL_ID_FLASH', pro:'MODEL_ID_PRO', thinking:'MODEL_ID_THINKING'};
        document.getElementById(map[type]).value = id;
    }

    function loadConfigData() {
        if (configLoaded) return;
        fetch('/admin/config', {credentials:'same-origin'}).then(function(r) {
            if (!r.ok) throw new Error('未登录');
            return r.json();
        }).then(function(config) {
            configLoaded = true;
            if (config.FULL_COOKIE) {
                document.getElementById('FULL_COOKIE').value = config.FULL_COOKIE;
                showParsedFields(parseCookie(config.FULL_COOKIE));
            }
            if (config.MODEL_IDS) {
                document.getElementById('MODEL_ID_FLASH').value = config.MODEL_IDS.flash || '';
                document.getElementById('MODEL_ID_PRO').value = config.MODEL_IDS.pro || '';
                document.getElementById('MODEL_ID_THINKING').value = config.MODEL_IDS.thinking || '';
            }
        }).catch(function(e) { console.log('加载配置失败:', e); });
    }

    // Cookie input listener
    document.getElementById('FULL_COOKIE').addEventListener('input', function(e) {
        showParsedFields(parseCookie(e.target.value));
    });

    // Model ID parser listener
    document.getElementById('MODEL_ID_PARSER').addEventListener('input', function(e) {
        var mid = parseModelId(e.target.value);
        var container = document.getElementById('parsedModelIdValue');
        var box = document.getElementById('parsedModelId');
        if (mid) {
            container.innerHTML = '';
            var info = document.createElement('div');
            info.className = 'item';
            info.innerHTML = '提取到的 ID: <span style="color:#4ade80;font-family:monospace;">' + mid + '</span>';
            container.appendChild(info);

            var btnWrap = document.createElement('div');
            btnWrap.style.marginTop = '10px';

            ['flash', 'pro', 'thinking'].forEach(function(type) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.style.marginRight = '5px';
                btn.style.padding = '5px 10px';
                btn.style.cursor = 'pointer';
                btn.style.background = '#2a2a4a';
                btn.style.color = '#e0e0e0';
                btn.style.border = '1px solid #3a3a5a';
                btn.style.borderRadius = '4px';
                btn.textContent = type === 'flash' ? '填入极速版' : (type === 'pro' ? '填入Pro版' : '填入思考版');
                btn.addEventListener('click', function() {
                    fillModelId(type, mid);
                });
                btnWrap.appendChild(btn);
            });

            container.appendChild(btnWrap);
            box.style.display = 'block';
        } else {
            box.style.display = 'none';
        }
    });

    // Config form submit
    document.getElementById('configForm').addEventListener('submit', async function(e) {
        e.preventDefault();
        var formData = new FormData(e.target);
        var data = {};
        formData.forEach(function(v, k) { data[k] = v; });
        data.MODEL_IDS = {
            flash: data.MODEL_ID_FLASH || '',
            pro: data.MODEL_ID_PRO || '',
            thinking: data.MODEL_ID_THINKING || ''
        };
        delete data.MODEL_ID_FLASH;
        delete data.MODEL_ID_PRO;
        delete data.MODEL_ID_THINKING;

        var statusEl = document.getElementById('cfgStatus');
        statusEl.className = 'status-msg';
        statusEl.style.display = 'none';

        var btn = e.target.querySelector('button[type="submit"]');
        var origText = btn.textContent;
        btn.textContent = '保存中...';
        btn.disabled = true;

        try {
            var resp = await fetch('/admin/save', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify(data)
            });
            if (resp.status === 401) { location.href = '/admin/login'; return; }
            var result = await resp.json();
            if (result.success) {
                statusEl.className = 'status-msg success';
                statusEl.innerHTML = '&#10004; ' + result.message + '<br><br>配置已生效，无需重启服务！';
            } else {
                statusEl.className = 'status-msg error';
                statusEl.textContent = '&#10008; ' + result.message;
            }
            statusEl.style.display = 'block';
            updateTokenBadge();
        } catch(err) {
            statusEl.className = 'status-msg error';
            statusEl.textContent = '保存失败: ' + err.message;
            statusEl.style.display = 'block';
        } finally {
            btn.textContent = origText;
            btn.disabled = false;
        }
    });

// ===== Init =====
var currentUser = (document.cookie.match(/(?:^|;\s*)admin_username=([^;]*)/) || [,'用户'])[1];
var isAdmin = (document.cookie.match(/(?:^|;\s*)admin_is_admin=([^;]*)/) || [,'0'])[1] === '1';
if (!isAdmin) {
document.querySelectorAll('.nav-item').forEach(function(el) {
var onclick = el.getAttribute('onclick') || '';
if (onclick.indexOf('users') > -1 || onclick.indexOf('config') > -1) el.style.display = 'none';
});
document.querySelectorAll('.admin-only-btn').forEach(function(el) { el.style.display = 'none'; });
}
function getGreeting() {
        var h = new Date().getHours();
        if (h < 6) return '夜深了';
        if (h < 12) return '早上好';
        if (h < 14) return '中午好';
        if (h < 18) return '下午好';
        return '晚上好';
    }
var greetingEl = document.getElementById('greetingText');
if (greetingEl) greetingEl.textContent = getGreeting() + '，' + currentUser;

// ===== Image Lightbox =====
function openImgLightbox(src) {
var lb = document.getElementById('imgLightbox');
document.getElementById('lbImg').src = src;
lb.classList.add('active');
document.addEventListener('keydown', _lbKeyHandler);
}
function closeImgLightbox() {
  var lb = document.getElementById('imgLightbox');
  lb.classList.remove('active');
  document.getElementById('lbImg').src = '';
  document.removeEventListener('keydown', _lbKeyHandler);
}
function _lbKeyHandler(e) { if (e.key === 'Escape') closeImgLightbox(); }

// ===== User Message Actions =====
function copyMsg(btn) {
  var msgDiv = btn.closest('.msg.user');
  var textEl = msgDiv.querySelector('.msg-time');
  var cloned = msgDiv.cloneNode(true);
  cloned.querySelectorAll('.msg-actions').forEach(function(el){ el.remove(); });
  cloned.querySelectorAll('.msg-time').forEach(function(el){ el.remove(); });
  var text = cloned.textContent.trim();
  navigator.clipboard.writeText(text).then(function(){
    btn.textContent = '\u5df2\u590d\u5236';
    setTimeout(function(){ btn.textContent = '\u590d\u5236'; }, 1500);
  });
}
function editMsg(btn) {
  var msgDiv = btn.closest('.msg.user');
  var cloned = msgDiv.cloneNode(true);
  cloned.querySelectorAll('.msg-actions').forEach(function(el){ el.remove(); });
  cloned.querySelectorAll('.msg-time').forEach(function(el){ el.remove(); });
  var text = cloned.textContent.trim();
  // Find this message's index in chatHistory
  var msgs = document.getElementById('chatMessages').children;
  var msgIdx = -1;
  for (var i = 0; i < msgs.length; i++) {
    if (msgs[i] === msgDiv) { msgIdx = i; break; }
  }
  // Remove all messages from this one onward
  var toRemove = [];
  for (var j = msgIdx; j < msgs.length; j++) toRemove.push(msgs[j]);
  toRemove.forEach(function(el){ el.remove(); });
  // Truncate chatHistory: count user+assistant pairs up to this point
  var historyIdx = 0;
  var count = 0;
  for (var k = 0; k < chatHistory.length; k++) {
    if (count >= msgIdx) { historyIdx = k; break; }
    count++;
  }
  if (count < msgIdx) historyIdx = chatHistory.length;
  chatHistory = chatHistory.slice(0, historyIdx);
  // Put text back in input
  var input = document.getElementById('chatInput');
  input.value = text;
  input.focus();
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 120) + 'px';
}

// Expose functions to global scope for onclick handlers
window.switchTab = switchTab;
window.toggleTheme = toggleTheme;
window.sendMessage = sendMessage;
window.openImgLightbox = openImgLightbox;
window.closeImgLightbox = closeImgLightbox;
window.copyMsg = copyMsg;
window.editMsg = editMsg;