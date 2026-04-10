const state = {
    chatId: null,
    chatTitle: "",
    messages: [],
    isGenerating: false,
    thinkEnabled: false,
    autoScroll: true,
    thinkingStartTime: null,
    currentThinkingText: "",
    currentContentText: "",
    sidebarOpen: true,
};

function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

const $messages = document.getElementById("messages");
const $welcome = document.getElementById("welcome");
const $input = document.getElementById("input");
const $sendBtn = document.getElementById("send-btn");
const $stopBtn = document.getElementById("stop-btn");
const $thinkToggle = document.getElementById("think-toggle");
const $statusText = document.getElementById("status-text");
const $schedulePanel = document.getElementById("schedule-panel");
const $scheduleBtn = document.getElementById("schedule-btn");
const $scheduleList = document.getElementById("schedule-list");
const $sidebar = document.getElementById("sidebar");
const $historyList = document.getElementById("history-list");
const $newChatBtn = document.getElementById("new-chat-btn");
const $sidebarToggle = document.getElementById("sidebar-toggle");
const $projectBtn = document.getElementById("project-btn");
const $projectLabel = document.getElementById("project-label");

let currentAssistantEl = null;
let currentContentEl = null;
let currentThinkingEl = null;
let currentThinkingSummary = null;
let renderTimer = null;

// --- Marked config ---
marked.setOptions({
    breaks: true,
    gfm: true,
});

// --- Event listeners ---

$thinkToggle.addEventListener("click", () => {
    state.thinkEnabled = !state.thinkEnabled;
    $thinkToggle.classList.toggle("active", state.thinkEnabled);
});

$input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

$input.addEventListener("input", () => {
    autoGrowTextarea();
    $sendBtn.disabled = !$input.value.trim();
});

$sendBtn.addEventListener("click", sendMessage);
$stopBtn.addEventListener("click", stopGeneration);

$scheduleBtn.addEventListener("click", () => {
    $schedulePanel.classList.toggle("open");
    if ($schedulePanel.classList.contains("open")) {
        refreshSchedules();
    }
});

document.getElementById("schedule-close").addEventListener("click", () => {
    $schedulePanel.classList.remove("open");
});

$newChatBtn.addEventListener("click", () => newChat());

$sidebarToggle.addEventListener("click", () => {
    state.sidebarOpen = !state.sidebarOpen;
    $sidebar.classList.toggle("collapsed", !state.sidebarOpen);
});

$projectBtn.addEventListener("click", () => {
    if ($projectBtn.classList.contains("active")) {
        // Clear project
        window.pywebview.api.clear_project_folder().then(() => {
            $projectBtn.classList.remove("active");
            $projectLabel.textContent = "Project";
            $projectBtn.title = "Set project folder";
            showToast("Project folder cleared");
        });
    } else {
        // Pick folder
        window.pywebview.api.pick_project_folder().then((raw) => {
            const result = JSON.parse(raw);
            if (result.path) {
                const name = result.path.split("/").pop();
                $projectBtn.classList.add("active");
                $projectLabel.textContent = name;
                $projectBtn.title = result.path + " (click to clear)";
                showToast("Project set: " + name);
            }
        });
    }
});

// Auto-scroll detection
$messages.addEventListener("scroll", () => {
    const { scrollTop, scrollHeight, clientHeight } = $messages;
    state.autoScroll = scrollHeight - scrollTop - clientHeight < 40;
});

// --- Functions ---

function autoGrowTextarea() {
    $input.style.height = "auto";
    $input.style.height = Math.min($input.scrollHeight, 150) + "px";
}

function scrollToBottom() {
    if (state.autoScroll) {
        $messages.scrollTop = $messages.scrollHeight;
    }
}

function sendMessage() {
    const text = $input.value.trim();
    if (!text || state.isGenerating) return;

    // Hide welcome
    if ($welcome) $welcome.style.display = "none";

    // Create chat ID on first message
    if (!state.chatId) {
        state.chatId = generateId();
        state.chatTitle = text.slice(0, 60);
    }

    // Add user message
    state.messages.push({ role: "user", content: text });
    appendUserMessage(text);

    // Clear input
    $input.value = "";
    $input.style.height = "auto";
    $sendBtn.disabled = true;

    // Prepare assistant placeholder
    createAssistantPlaceholder();

    // Start generation
    state.isGenerating = true;
    state.currentThinkingText = "";
    state.currentContentText = "";
    state.thinkingStartTime = null;
    $sendBtn.style.display = "none";
    $stopBtn.style.display = "flex";
    $input.disabled = true;
    $statusText.textContent = "Working...";

    // Send messages (filter to only role+content for API, tool messages included)
    const messagesForApi = state.messages.map((m) => {
        const msg = { role: m.role, content: m.content };
        if (m.tool_calls) msg.tool_calls = m.tool_calls;
        return msg;
    });
    window.pywebview.api
        .send_message(JSON.stringify(messagesForApi), state.thinkEnabled)
        .catch((err) => {
            window.onStreamError(err.toString());
        });
}

function stopGeneration() {
    window.pywebview.api.stop_generation();
}

function appendUserMessage(text) {
    const el = document.createElement("div");
    el.className = "message message-user";
    el.innerHTML = `
        <div class="message-label">You</div>
        <div class="message-content">${escapeHtml(text)}</div>
    `;
    $messages.appendChild(el);
    scrollToBottom();
}

function createAssistantPlaceholder() {
    currentAssistantEl = document.createElement("div");
    currentAssistantEl.className = "message message-assistant";

    const label = document.createElement("div");
    label.className = "message-label";
    label.textContent = "Gemma";

    currentContentEl = document.createElement("div");
    currentContentEl.className = "message-content";
    currentContentEl.innerHTML = '<span class="cursor"></span>';

    currentAssistantEl.appendChild(label);
    currentAssistantEl.appendChild(currentContentEl);
    $messages.appendChild(currentAssistantEl);

    currentThinkingEl = null;
    currentThinkingSummary = null;
    scrollToBottom();
}

function createThinkingSection() {
    const section = document.createElement("div");
    section.className = "thinking-section open";

    const summary = document.createElement("div");
    summary.className = "thinking-summary";
    summary.innerHTML =
        '<span class="thinking-arrow">&#9654;</span> <span class="thinking-label loading-dots">Thinking</span>';
    summary.addEventListener("click", () => {
        section.classList.toggle("open");
    });

    const content = document.createElement("div");
    content.className = "thinking-content";

    section.appendChild(summary);
    section.appendChild(content);

    currentAssistantEl.insertBefore(section, currentContentEl);

    currentThinkingEl = content;
    currentThinkingSummary = summary;
    state.thinkingStartTime = Date.now();
}

// --- Tool call UI ---

function appendToolBlock(name, args) {
    const block = document.createElement("div");
    block.className = "tool-block";
    block.id = "tool-" + Date.now();

    const header = document.createElement("div");
    header.className = "tool-header";

    const icon = document.createElement("span");
    icon.className = "tool-icon";
    icon.textContent = getToolIcon(name);

    const label = document.createElement("span");
    label.className = "tool-name";
    label.textContent = name;

    const argsEl = document.createElement("span");
    argsEl.className = "tool-args";
    argsEl.textContent = formatToolArgs(name, args);

    const spinner = document.createElement("span");
    spinner.className = "tool-spinner";

    header.appendChild(icon);
    header.appendChild(label);
    header.appendChild(argsEl);
    header.appendChild(spinner);

    block.appendChild(header);
    currentAssistantEl.insertBefore(block, currentContentEl);
    scrollToBottom();
    return block;
}

function setToolResult(block, name, result) {
    // Remove spinner
    const spinner = block.querySelector(".tool-spinner");
    if (spinner) spinner.remove();

    // Add checkmark
    const check = document.createElement("span");
    check.className = "tool-done";
    check.textContent = " done";
    block.querySelector(".tool-header").appendChild(check);

    // Add output
    if (result && result.trim()) {
        const output = document.createElement("div");
        output.className = "tool-output";

        const toggle = document.createElement("div");
        toggle.className = "tool-output-toggle";
        toggle.textContent = "Show output";
        toggle.addEventListener("click", () => {
            output.classList.toggle("expanded");
            toggle.textContent = output.classList.contains("expanded")
                ? "Hide output"
                : "Show output";
        });

        const pre = document.createElement("pre");
        pre.textContent = result;

        output.appendChild(toggle);
        output.appendChild(pre);
        block.appendChild(output);
    }
    scrollToBottom();
}

function getToolIcon(name) {
    const icons = {
        run_command: ">_",
        read_file: "R",
        write_file: "W",
        list_directory: "D",
        search_files: "?",
        create_document: "F",
        manage_schedule: "S",
    };
    return icons[name] || "T";
}

function formatToolArgs(name, args) {
    if (name === "run_command") return args.command || "";
    if (name === "read_file" || name === "list_directory") return args.path || "";
    if (name === "write_file") return args.path || "";
    if (name === "search_files") return args.pattern || "";
    if (name === "create_document") return `${args.format}: ${args.path || ""}`;
    if (name === "manage_schedule") return args.action || "";
    return JSON.stringify(args);
}

// --- Streaming callbacks (called from Python) ---

let currentToolBlock = null;

window.onStreamChunk = function (type, token) {
    if (type === "thinking") {
        if (!currentThinkingEl) {
            createThinkingSection();
        }
        state.currentThinkingText += token;
        currentThinkingEl.textContent = state.currentThinkingText;
        currentThinkingEl.scrollTop = currentThinkingEl.scrollHeight;
    } else {
        if (currentThinkingSummary && state.thinkingStartTime) {
            finalizeThinking();
        }
        state.currentContentText += token;
        scheduleRender();
    }
    scrollToBottom();
};

window.onToolCall = function (data) {
    if (currentThinkingSummary && state.thinkingStartTime) {
        finalizeThinking();
    }
    $statusText.textContent = `Running: ${data.name}...`;
    currentToolBlock = appendToolBlock(data.name, data.args);
};

window.onToolResult = function (data) {
    if (currentToolBlock) {
        setToolResult(currentToolBlock, data.name, data.result);
        currentToolBlock = null;
    }
    $statusText.textContent = "Working...";
};

window.onMessagesSync = function (messages) {
    // Replace state with full conversation history (includes tool messages)
    state.messages = messages;
};

window.onStreamEnd = function () {
    if (currentThinkingSummary && state.thinkingStartTime) {
        finalizeThinking();
    }
    // Final render
    renderContent();
    // Remove cursor
    const cursor = currentContentEl
        ? currentContentEl.querySelector(".cursor")
        : null;
    if (cursor) cursor.remove();

    // Auto-save conversation
    saveCurrentChat();

    finishGeneration();
};

window.onStreamError = function (error) {
    const cursor = currentContentEl
        ? currentContentEl.querySelector(".cursor")
        : null;
    if (cursor) cursor.remove();

    const errEl = document.createElement("div");
    errEl.className = "message-error";
    errEl.textContent = "Error: " + error;
    if (currentAssistantEl) currentAssistantEl.appendChild(errEl);

    finishGeneration();
};

window.onScheduleRun = function (data) {
    // Show a toast notification
    showToast(`Task "${data.task.name}" completed`);
    // Refresh panel if open
    if ($schedulePanel.classList.contains("open")) {
        refreshSchedules();
    }
};

function finalizeThinking() {
    const elapsed = ((Date.now() - state.thinkingStartTime) / 1000).toFixed(1);
    currentThinkingSummary.innerHTML = `<span class="thinking-arrow">&#9654;</span> Thought for ${elapsed}s`;
    currentThinkingSummary.closest(".thinking-section").classList.remove("open");
    state.thinkingStartTime = null;
}

function scheduleRender() {
    if (!renderTimer) {
        renderTimer = requestAnimationFrame(() => {
            renderContent();
            renderTimer = null;
        });
    }
}

function renderContent() {
    if (!currentContentEl) return;
    const html = marked.parse(state.currentContentText);
    currentContentEl.innerHTML = html + '<span class="cursor"></span>';
}

function finishGeneration() {
    state.isGenerating = false;
    $sendBtn.style.display = "flex";
    $stopBtn.style.display = "none";
    $input.disabled = false;
    $input.focus();
    $statusText.textContent = "";
    currentAssistantEl = null;
    currentContentEl = null;
    currentThinkingEl = null;
    currentThinkingSummary = null;
    currentToolBlock = null;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

// --- Schedule panel ---

function refreshSchedules() {
    window.pywebview.api.get_schedules().then((raw) => {
        const tasks = JSON.parse(raw);
        $scheduleList.innerHTML = "";
        if (tasks.length === 0) {
            $scheduleList.innerHTML =
                '<div class="schedule-empty">No scheduled tasks. Ask Gemma to create one!</div>';
            return;
        }
        tasks.forEach((t) => {
            const item = document.createElement("div");
            item.className = "schedule-item" + (t.enabled ? "" : " disabled");
            item.innerHTML = `
                <div class="schedule-item-header">
                    <span class="schedule-item-name">${escapeHtml(t.name)}</span>
                    <span class="schedule-item-interval">every ${t.interval_minutes}m</span>
                </div>
                <div class="schedule-item-prompt">${escapeHtml(t.prompt)}</div>
                <div class="schedule-item-status">
                    Last: ${t.last_run ? new Date(t.last_run * 1000).toLocaleTimeString() : "never"}
                </div>
                <div class="schedule-item-actions">
                    <button class="schedule-toggle-btn">${t.enabled ? "Disable" : "Enable"}</button>
                    <button class="schedule-delete-btn">Delete</button>
                </div>
            `;
            item.querySelector(".schedule-toggle-btn").addEventListener("click", () => {
                window.pywebview.api.toggle_schedule(t.id).then(() => refreshSchedules());
            });
            item.querySelector(".schedule-delete-btn").addEventListener("click", () => {
                window.pywebview.api.delete_schedule(t.id).then(() => refreshSchedules());
            });
            $scheduleList.appendChild(item);
        });
    });
}

// --- Toast notification ---

function showToast(message) {
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("visible"));
    setTimeout(() => {
        toast.classList.remove("visible");
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// --- Chat history ---

function saveCurrentChat() {
    if (!state.chatId || state.messages.length === 0) return;
    window.pywebview.api.save_chat(
        state.chatId,
        state.chatTitle,
        JSON.stringify(state.messages)
    ).then(() => refreshHistory());
}

function newChat() {
    if (state.isGenerating) return;
    state.chatId = null;
    state.chatTitle = "";
    state.messages = [];
    state.currentThinkingText = "";
    state.currentContentText = "";

    // Clear message area and show welcome
    $messages.innerHTML = "";
    const welcome = document.createElement("div");
    welcome.id = "welcome";
    welcome.className = "welcome";
    welcome.innerHTML = `
        <div class="welcome-icon">G</div>
        <h2>Gemma 4</h2>
        <p>Running locally via Ollama</p>
        <div class="welcome-capabilities">
            <span>Run commands</span>
            <span>Read & write files</span>
            <span>Create documents</span>
            <span>Schedule tasks</span>
        </div>
    `;
    $messages.appendChild(welcome);

    $input.value = "";
    $input.focus();
    $sendBtn.disabled = true;

    // Deselect in sidebar
    document.querySelectorAll(".history-item.active").forEach((el) => {
        el.classList.remove("active");
    });
}

function loadChat(chatId) {
    if (state.isGenerating) return;
    window.pywebview.api.load_chat(chatId).then((raw) => {
        const data = JSON.parse(raw);
        if (!data.id) return;

        state.chatId = data.id;
        state.chatTitle = data.title || "Untitled";
        state.messages = data.messages || [];

        // Re-render all messages
        $messages.innerHTML = "";
        let assistantContent = "";

        for (const msg of state.messages) {
            if (msg.role === "user") {
                appendUserMessage(msg.content);
            } else if (msg.role === "assistant") {
                const el = document.createElement("div");
                el.className = "message message-assistant";

                const label = document.createElement("div");
                label.className = "message-label";
                label.textContent = "Gemma";

                const content = document.createElement("div");
                content.className = "message-content";
                content.innerHTML = marked.parse(msg.content || "");

                el.appendChild(label);

                // Show tool calls if present
                if (msg.tool_calls) {
                    for (const tc of msg.tool_calls) {
                        const func = tc.function || {};
                        const block = document.createElement("div");
                        block.className = "tool-block";
                        block.innerHTML = `
                            <div class="tool-header">
                                <span class="tool-icon">${escapeHtml(getToolIcon(func.name))}</span>
                                <span class="tool-name">${escapeHtml(func.name || "")}</span>
                                <span class="tool-args">${escapeHtml(formatToolArgs(func.name, func.arguments || {}))}</span>
                                <span class="tool-done"> done</span>
                            </div>
                        `;
                        el.appendChild(block);
                    }
                }

                el.appendChild(content);
                $messages.appendChild(el);
            }
            // Skip "tool" and "system" role messages in rendering
        }

        scrollToBottom();

        // Highlight in sidebar
        document.querySelectorAll(".history-item.active").forEach((el) => {
            el.classList.remove("active");
        });
        const active = document.querySelector(`.history-item[data-id="${chatId}"]`);
        if (active) active.classList.add("active");
    });
}

function refreshHistory() {
    window.pywebview.api.list_chats().then((raw) => {
        const chats = JSON.parse(raw);
        $historyList.innerHTML = "";
        if (chats.length === 0) {
            $historyList.innerHTML =
                '<div class="history-empty">No conversations yet</div>';
            return;
        }
        chats.forEach((c) => {
            const item = document.createElement("div");
            item.className = "history-item" + (c.id === state.chatId ? " active" : "");
            item.dataset.id = c.id;

            const title = document.createElement("div");
            title.className = "history-item-title";
            title.textContent = c.title || "Untitled";

            const date = document.createElement("div");
            date.className = "history-item-date";
            date.textContent = formatDate(c.updated);

            const del = document.createElement("button");
            del.className = "history-item-delete";
            del.innerHTML = "&times;";
            del.title = "Delete";
            del.addEventListener("click", (e) => {
                e.stopPropagation();
                window.pywebview.api.delete_chat(c.id).then(() => {
                    if (state.chatId === c.id) newChat();
                    refreshHistory();
                });
            });

            item.appendChild(title);
            item.appendChild(date);
            item.appendChild(del);

            item.addEventListener("click", () => loadChat(c.id));
            $historyList.appendChild(item);
        });
    });
}

function formatDate(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    const now = new Date();
    if (d.toDateString() === now.toDateString()) {
        return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    if (d.toDateString() === yesterday.toDateString()) {
        return "Yesterday";
    }
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

// --- Init ---

window.addEventListener("pywebviewready", () => {
    window.pywebview.api.check_health().then((healthy) => {
        if (!healthy) {
            $statusText.textContent =
                "Ollama is not running. Start it with: brew services start ollama";
            $statusText.style.color = "#e54d4d";
        }
    });
    refreshHistory();
});

$sendBtn.disabled = true;
