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
    attachment: null,
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
const $uploadBtn = document.getElementById("upload-btn");
const $attachmentPreview = document.getElementById("attachment-preview");
const $projectBtn = document.getElementById("project-btn");
const $projectLabel = document.getElementById("project-label");
const $mcpBtn = document.getElementById("mcp-btn");
const $mcpPanel = document.getElementById("mcp-panel");
const $mcpServers = document.getElementById("mcp-servers");
const $skillsBtn = document.getElementById("skills-btn");
const $skillsPanel = document.getElementById("skills-panel");
const $skillsList = document.getElementById("skills-list");

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

$uploadBtn.addEventListener("click", () => {
    window.pywebview.api.pick_file().then((raw) => {
        const result = JSON.parse(raw);
        if (!result.ok) {
            if (result.error) showToast(result.error);
            return;
        }
        state.attachment = result;
        $attachmentPreview.style.display = "flex";
        $attachmentPreview.innerHTML = `
            <span class="attachment-name">${escapeHtml(result.name)}</span>
            <span class="attachment-size">${formatFileSize(result.size)}</span>
            <button class="attachment-remove">&times;</button>
        `;
        $attachmentPreview.querySelector(".attachment-remove").addEventListener("click", () => {
            state.attachment = null;
            $attachmentPreview.style.display = "none";
        });
        $sendBtn.disabled = false;
    });
});

$sidebarToggle.addEventListener("click", () => {
    state.sidebarOpen = !state.sidebarOpen;
    $sidebar.classList.toggle("collapsed", !state.sidebarOpen);
});

$mcpBtn.addEventListener("click", () => {
    $mcpPanel.classList.toggle("open");
    if ($mcpPanel.classList.contains("open")) {
        refreshMCP();
    }
});

$skillsBtn.addEventListener("click", () => {
    $skillsPanel.classList.toggle("open");
    if ($skillsPanel.classList.contains("open")) {
        refreshSkills();
    }
});

document.getElementById("skills-close").addEventListener("click", () => {
    $skillsPanel.classList.remove("open");
});

document.getElementById("skills-rescan").addEventListener("click", () => {
    window.pywebview.api.rescan_skills().then(() => {
        refreshSkills();
        showToast("Skills rescanned");
    });
});

document.getElementById("mcp-close").addEventListener("click", () => {
    $mcpPanel.classList.remove("open");
});

document.getElementById("mcp-add-btn").addEventListener("click", () => {
    const name = document.getElementById("mcp-name").value.trim();
    const command = document.getElementById("mcp-command").value.trim();
    const args = document.getElementById("mcp-args").value.trim() || "[]";
    const env = document.getElementById("mcp-env").value.trim() || "{}";
    if (!name || !command) {
        showToast("Name and command are required");
        return;
    }
    document.getElementById("mcp-add-btn").textContent = "Connecting...";
    window.pywebview.api.add_mcp_server(name, command, args, env).then((raw) => {
        const result = JSON.parse(raw);
        if (result.ok) {
            showToast("Server added and connected");
            document.getElementById("mcp-name").value = "";
            document.getElementById("mcp-command").value = "";
            document.getElementById("mcp-args").value = "";
            document.getElementById("mcp-env").value = "";
        } else {
            showToast("Error: " + (result.error || "Failed to connect"));
        }
        document.getElementById("mcp-add-btn").textContent = "Add & Connect";
        refreshMCP();
    });
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
    if ((!text && !state.attachment) || state.isGenerating) return;

    // Hide welcome
    if ($welcome) $welcome.style.display = "none";

    // Create chat ID on first message
    if (!state.chatId) {
        state.chatId = generateId();
        state.chatTitle = (text || state.attachment?.name || "").slice(0, 60);
    }

    // Build message content — include attachment if present
    let content = text;
    if (state.attachment) {
        const fileHeader = `[Attached file: ${state.attachment.name}]\n\n`;
        content = text
            ? `${text}\n\n${fileHeader}${state.attachment.content}`
            : `${fileHeader}${state.attachment.content}`;
    }

    // Add user message
    state.messages.push({ role: "user", content: content });
    appendUserMessage(text, state.attachment);

    // Clear attachment
    state.attachment = null;
    $attachmentPreview.style.display = "none";

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
        .send_message(JSON.stringify(messagesForApi), state.thinkEnabled, state.chatId || "")
        .catch((err) => {
            window.onStreamError(err.toString());
        });
}

function stopGeneration() {
    window.pywebview.api.stop_generation();
}

function appendUserMessage(text, attachment) {
    const el = document.createElement("div");
    el.className = "message message-user";
    let html = '<div class="message-label">You</div>';
    if (attachment) {
        html += `<div class="message-attachment">
            <span class="attachment-icon">F</span>
            <span>${escapeHtml(attachment.name)}</span>
            <span class="attachment-size">${formatFileSize(attachment.size)}</span>
        </div>`;
    }
    if (text) {
        html += `<div class="message-content">${escapeHtml(text)}</div>`;
    }
    el.innerHTML = html;
    $messages.appendChild(el);
    scrollToBottom();
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
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

// --- PML Dashboard ---

const $pmlPanel = document.getElementById("pml-panel");
const $pmlBtn = document.getElementById("pml-btn");
const $pmlPatients = document.getElementById("pml-patients");
const $pmlPipeline = document.getElementById("pml-pipeline");
const $pmlAddForm = document.getElementById("pml-add-form");
const $pmlAddBtn = document.getElementById("pml-add-btn");

$pmlBtn.addEventListener("click", () => {
    $pmlPanel.classList.toggle("open");
    if ($pmlPanel.classList.contains("open")) refreshPML();
});

document.getElementById("pml-close").addEventListener("click", () => {
    $pmlPanel.classList.remove("open");
});

$pmlAddBtn.addEventListener("click", () => {
    $pmlAddForm.style.display = "block";
    $pmlAddBtn.style.display = "none";
});

document.getElementById("pml-add-cancel").addEventListener("click", () => {
    $pmlAddForm.style.display = "none";
    $pmlAddBtn.style.display = "block";
});

document.getElementById("pml-f-has-therapist").addEventListener("change", (e) => {
    document.getElementById("pml-therapist-fields").style.display = e.target.checked ? "block" : "none";
});

document.getElementById("pml-add-submit").addEventListener("click", () => {
    const name = document.getElementById("pml-f-name").value.trim();
    if (!name) { showToast("Patient name required"); return; }
    const clinician = document.getElementById("pml-f-clinician").value.trim() || "Dr. Al-Katib";
    const weeks = document.getElementById("pml-f-weeks").value || "4";
    const hasTherapist = document.getElementById("pml-f-has-therapist").checked;
    const therapistName = document.getElementById("pml-f-therapist-name")?.value.trim() || "";
    const therapistContact = document.getElementById("pml-f-therapist-contact")?.value.trim() || "";

    window.pywebview.api.pml_add_patient(name, clinician, weeks, hasTherapist, therapistName, therapistContact)
        .then(() => {
            showToast(`PML track created for ${name}`);
            $pmlAddForm.style.display = "none";
            $pmlAddBtn.style.display = "block";
            document.getElementById("pml-f-name").value = "";
            document.getElementById("pml-f-has-therapist").checked = false;
            document.getElementById("pml-therapist-fields").style.display = "none";
            refreshPML();
        });
});

function refreshPML() {
    // Pipeline summary
    window.pywebview.api.pml_get_pipeline().then((raw) => {
        const pipeline = JSON.parse(raw);
        const labels = {
            initiated: "New", patient_contacted: "Contacted", awaiting_therapist_info: "Info",
            roi_sent: "ROI Sent", therapy_referral: "Referral", roi_verified: "Verified",
            visit2_ready: "Visit 2", forms_completed: "Done", active_monitoring: "Active",
        };
        const pills = Object.entries(pipeline).map(([s, c]) =>
            `<span class="pml-pipeline-pill">${labels[s] || s}: ${c}</span>`
        ).join("");
        $pmlPipeline.innerHTML = pills || '<span class="pml-pipeline-empty">No patients yet</span>';
    });

    // Patient list
    window.pywebview.api.pml_get_patients().then((raw) => {
        const patients = JSON.parse(raw);
        $pmlPatients.innerHTML = "";
        if (patients.length === 0) {
            $pmlPatients.innerHTML = '<div class="schedule-empty">No PML patients. Click below to add one.</div>';
            return;
        }
        const statusLabels = {
            initiated: "Initiated", patient_contacted: "Contacted",
            awaiting_therapist_info: "Awaiting Info", roi_sent: "ROI Sent",
            therapy_referral: "Needs Referral", roi_verified: "ROI Verified",
            visit2_ready: "Ready for Visit 2", forms_completed: "Forms Done",
            active_monitoring: "Active",
        };
        const statusColors = {
            initiated: "#7c6bf5", patient_contacted: "#4a9eff", awaiting_therapist_info: "#d4a843",
            roi_sent: "#d4a843", therapy_referral: "#e54d4d", roi_verified: "#4ade80",
            visit2_ready: "#4ade80", forms_completed: "#4ade80", active_monitoring: "#888",
        };
        patients.forEach((p) => {
            const card = document.createElement("div");
            card.className = "pml-patient-card";
            const color = statusColors[p.status] || "#888";
            const roiInfo = p.roi_sent_date && !p.roi_returned
                ? `<div class="pml-roi-warning">ROI sent ${p.roi_sent_date}</div>` : "";
            card.innerHTML = `
                <div class="pml-card-header">
                    <div class="pml-card-name">${escapeHtml(p.name)}</div>
                    <button class="pml-card-delete" title="Remove">&times;</button>
                </div>
                <div class="pml-card-meta">${escapeHtml(p.clinician)} &middot; ${p.weeks} weeks</div>
                <div class="pml-card-status" style="color:${color}">${statusLabels[p.status] || p.status}</div>
                ${roiInfo}
                <div class="pml-card-actions">
                    <button class="pml-scripts-btn">Scripts</button>
                    <button class="pml-advance-btn">Next Step</button>
                </div>
                <div class="pml-scripts-dropdown" style="display:none"></div>
            `;

            card.querySelector(".pml-card-delete").addEventListener("click", () => {
                window.pywebview.api.pml_delete_patient(p.id).then(() => {
                    refreshPML();
                    showToast(`${p.name} removed`);
                });
            });

            card.querySelector(".pml-advance-btn").addEventListener("click", () => {
                window.pywebview.api.pml_advance_patient(p.id).then(() => {
                    refreshPML();
                    showToast(`${p.name} advanced`);
                });
            });

            const scriptsBtn = card.querySelector(".pml-scripts-btn");
            const dropdown = card.querySelector(".pml-scripts-dropdown");
            scriptsBtn.addEventListener("click", () => {
                if (dropdown.style.display === "none") {
                    window.pywebview.api.pml_get_patient_scripts(p.id).then((raw) => {
                        const scripts = JSON.parse(raw);
                        dropdown.innerHTML = "";
                        Object.entries(scripts).forEach(([key, desc]) => {
                            const btn = document.createElement("button");
                            btn.className = "pml-script-item";
                            btn.textContent = desc;
                            btn.addEventListener("click", () => {
                                window.pywebview.api.pml_get_script_text(p.id, key).then((text) => {
                                    navigator.clipboard.writeText(text).then(() => {
                                        showToast("Script copied to clipboard!");
                                    });
                                });
                            });
                            dropdown.appendChild(btn);
                        });
                        dropdown.style.display = "block";
                    });
                } else {
                    dropdown.style.display = "none";
                }
            });

            $pmlPatients.appendChild(card);
        });
    });
}

// --- MCP panel ---

const MCP_CATALOG = [
    {
        id: "github",
        name: "GitHub",
        description: "Search repos, read issues, create PRs",
        icon: "GH",
        command: "npx",
        args: ["-y", "@modelcontextprotocol/server-github"],
        envKeys: [{ key: "GITHUB_PERSONAL_ACCESS_TOKEN", label: "Personal Access Token", placeholder: "ghp_..." }],
    },
    {
        id: "filesystem",
        name: "Filesystem",
        description: "Secure read/write access to specific folders",
        icon: "FS",
        command: "npx",
        args: ["-y", "@modelcontextprotocol/server-filesystem"],
        extraArgs: true,
        extraArgsLabel: "Allowed directories (comma-separated)",
        extraArgsPlaceholder: "/Users/you/Documents, /Users/you/Projects",
        envKeys: [],
    },
    {
        id: "brave-search",
        name: "Brave Search",
        description: "Web search via Brave Search API",
        icon: "BS",
        command: "npx",
        args: ["-y", "@modelcontextprotocol/server-brave-search"],
        envKeys: [{ key: "BRAVE_API_KEY", label: "API Key", placeholder: "BSA..." }],
    },
    {
        id: "google-maps",
        name: "Google Maps",
        description: "Geocoding, directions, place search",
        icon: "GM",
        command: "npx",
        args: ["-y", "@modelcontextprotocol/server-google-maps"],
        envKeys: [{ key: "GOOGLE_MAPS_API_KEY", label: "API Key", placeholder: "AIza..." }],
    },
    {
        id: "slack",
        name: "Slack",
        description: "Read channels, send messages, search",
        icon: "SL",
        command: "npx",
        args: ["-y", "@modelcontextprotocol/server-slack"],
        envKeys: [
            { key: "SLACK_BOT_TOKEN", label: "Bot Token", placeholder: "xoxb-..." },
            { key: "SLACK_TEAM_ID", label: "Team ID", placeholder: "T0..." },
        ],
    },
    {
        id: "postgres",
        name: "PostgreSQL",
        description: "Query and manage PostgreSQL databases",
        icon: "PG",
        command: "npx",
        args: ["-y", "@modelcontextprotocol/server-postgres"],
        envKeys: [{ key: "POSTGRES_CONNECTION_STRING", label: "Connection String", placeholder: "postgresql://user:pass@host/db" }],
    },
];

const $mcpActive = document.getElementById("mcp-active");
const $mcpCatalog = document.getElementById("mcp-catalog");

function refreshMCP() {
    window.pywebview.api.get_mcp_status().then((raw) => {
        const status = JSON.parse(raw);
        const connectedNames = new Set(Object.keys(status));

        // Render active connections
        $mcpActive.innerHTML = "";
        connectedNames.forEach((name) => {
            const s = status[name];
            const catalogEntry = MCP_CATALOG.find((c) => c.id === name);
            const displayName = catalogEntry ? catalogEntry.name : name;
            const icon = catalogEntry ? catalogEntry.icon : name.slice(0, 2).toUpperCase();
            const dot = s.connected ? "mcp-dot-on" : "mcp-dot-off";
            const toolCount = s.tools.length;

            const item = document.createElement("div");
            item.className = "mcp-active-item";
            item.innerHTML = `
                <div class="mcp-active-icon">${escapeHtml(icon)}</div>
                <div class="mcp-active-info">
                    <div class="mcp-active-name">
                        <span class="${dot}"></span>
                        ${escapeHtml(displayName)}
                    </div>
                    <div class="mcp-active-tools">${toolCount} tool${toolCount !== 1 ? "s" : ""} available</div>
                </div>
                <button class="mcp-remove-btn" title="Disconnect">&times;</button>
            `;
            item.querySelector(".mcp-remove-btn").addEventListener("click", () => {
                window.pywebview.api.remove_mcp_server(name).then(() => {
                    refreshMCP();
                    showToast(`${displayName} disconnected`);
                });
            });
            $mcpActive.appendChild(item);
        });

        // Render catalog (only show unconnected)
        $mcpCatalog.innerHTML = "";
        MCP_CATALOG.forEach((entry) => {
            if (connectedNames.has(entry.id)) return;

            const card = document.createElement("div");
            card.className = "mcp-catalog-card";
            card.innerHTML = `
                <div class="mcp-catalog-icon">${entry.icon}</div>
                <div class="mcp-catalog-info">
                    <div class="mcp-catalog-name">${escapeHtml(entry.name)}</div>
                    <div class="mcp-catalog-desc">${escapeHtml(entry.description)}</div>
                </div>
            `;
            card.addEventListener("click", () => showConnectorSetup(entry));
            $mcpCatalog.appendChild(card);
        });
    });
}

function showConnectorSetup(entry) {
    // Replace catalog with setup form
    $mcpCatalog.innerHTML = "";
    const form = document.createElement("div");
    form.className = "mcp-setup-form";

    let fieldsHtml = "";
    entry.envKeys.forEach((ek) => {
        fieldsHtml += `
            <label class="mcp-setup-label">${escapeHtml(ek.label)}</label>
            <input class="mcp-setup-input" data-env-key="${ek.key}" type="password"
                   placeholder="${escapeHtml(ek.placeholder)}" />
        `;
    });
    if (entry.extraArgs) {
        fieldsHtml += `
            <label class="mcp-setup-label">${escapeHtml(entry.extraArgsLabel)}</label>
            <input class="mcp-setup-input" id="mcp-extra-args"
                   placeholder="${escapeHtml(entry.extraArgsPlaceholder)}" />
        `;
    }

    form.innerHTML = `
        <div class="mcp-setup-header">
            <div class="mcp-catalog-icon">${entry.icon}</div>
            <div>
                <div class="mcp-catalog-name">${escapeHtml(entry.name)}</div>
                <div class="mcp-catalog-desc">${escapeHtml(entry.description)}</div>
            </div>
        </div>
        ${fieldsHtml}
        <div class="mcp-setup-buttons">
            <button class="mcp-setup-cancel">Cancel</button>
            <button class="mcp-setup-connect">Connect</button>
        </div>
    `;

    form.querySelector(".mcp-setup-cancel").addEventListener("click", () => refreshMCP());
    form.querySelector(".mcp-setup-connect").addEventListener("click", () => {
        const env = {};
        form.querySelectorAll("[data-env-key]").forEach((input) => {
            const val = input.value.trim();
            if (val) env[input.dataset.envKey] = val;
        });

        let args = [...entry.args];
        if (entry.extraArgs) {
            const extra = (form.querySelector("#mcp-extra-args")?.value || "").trim();
            if (extra) {
                args = args.concat(extra.split(",").map((s) => s.trim()).filter(Boolean));
            }
        }

        const connectBtn = form.querySelector(".mcp-setup-connect");
        connectBtn.textContent = "Connecting...";
        connectBtn.disabled = true;

        window.pywebview.api
            .add_mcp_server(entry.id, entry.command, JSON.stringify(args), JSON.stringify(env))
            .then((raw) => {
                const result = JSON.parse(raw);
                if (result.ok) {
                    showToast(`${entry.name} connected!`);
                } else {
                    showToast("Error: " + (result.error || "Failed to connect"));
                }
                refreshMCP();
            });
    });

    $mcpCatalog.appendChild(form);
}

// --- Skills panel ---

const STATUS_LABEL = {
    ready: "Ready",
    disabled: "Disabled",
    missing_bin: "Missing binary",
    missing_env: "Missing env var",
    missing_python: "Missing package",
    load_error: "Load error",
};

function refreshSkills() {
    window.pywebview.api.get_skills_status().then((raw) => {
        const skills = JSON.parse(raw);
        $skillsList.innerHTML = "";
        if (skills.length === 0) {
            $skillsList.innerHTML = '<div class="skills-empty">No skills installed.</div>';
            return;
        }
        skills.forEach((s) => {
            const row = document.createElement("div");
            row.className = "skill-row";
            const dotClass = s.status === "ready" ? "skill-dot-on" : "skill-dot-off";
            const icon = s.emoji || s.name.slice(0, 2).toUpperCase();
            const statusText = STATUS_LABEL[s.status] || s.status;
            const detail = s.status_detail ? ` — ${escapeHtml(s.status_detail)}` : "";
            const enabled = s.enabled ? "checked" : "";
            const pinned = s.pinned ? "checked" : "";

            let authBlock = "";
            if (s.auth_kind === "oauth" && s.auth) {
                if (!s.auth.configured) {
                    authBlock = `<div class="skill-auth-msg">Not configured — drop OAuth client JSON at data/google_oauth.json</div>`;
                } else if (s.auth.authed) {
                    authBlock = `
                        <div class="skill-auth-row">
                            <span class="skill-auth-status skill-auth-ok">Connected${s.auth.email ? " · " + escapeHtml(s.auth.email) : ""}</span>
                            <button class="skill-auth-btn skill-auth-disconnect">Disconnect</button>
                        </div>`;
                } else {
                    authBlock = `
                        <div class="skill-auth-row">
                            <span class="skill-auth-status skill-auth-off">Not connected</span>
                            <button class="skill-auth-btn skill-auth-connect">Connect</button>
                        </div>`;
                }
            }

            row.innerHTML = `
                <div class="skill-head">
                    <div class="skill-icon">${escapeHtml(icon)}</div>
                    <div class="skill-info">
                        <div class="skill-name">
                            <span class="${dotClass}"></span>
                            ${escapeHtml(s.name)}
                        </div>
                        <div class="skill-desc">${escapeHtml(s.description || "")}</div>
                        <div class="skill-status">${escapeHtml(statusText)}${detail} · ${s.tool_count} tool${s.tool_count !== 1 ? "s" : ""}</div>
                    </div>
                </div>
                ${authBlock}
                <div class="skill-controls">
                    <label><input type="checkbox" class="skill-enable" ${enabled}/> Enabled</label>
                    <label><input type="checkbox" class="skill-pin" ${pinned}/> Pin to new chats</label>
                </div>
            `;

            row.querySelector(".skill-enable").addEventListener("change", (e) => {
                window.pywebview.api.toggle_skill(s.name, e.target.checked).then(refreshSkills);
            });
            row.querySelector(".skill-pin").addEventListener("change", (e) => {
                window.pywebview.api.toggle_skill_pin(s.name, e.target.checked).then(refreshSkills);
            });

            const connectBtn = row.querySelector(".skill-auth-connect");
            if (connectBtn) {
                connectBtn.addEventListener("click", () => {
                    connectBtn.textContent = "Opening browser…";
                    connectBtn.disabled = true;
                    window.pywebview.api.gmail_connect();
                    // Completion comes via window.onGmailAuthResult
                });
            }
            const disconnectBtn = row.querySelector(".skill-auth-disconnect");
            if (disconnectBtn) {
                disconnectBtn.addEventListener("click", () => {
                    if (!confirm("Disconnect Gmail? Stored tokens will be deleted.")) return;
                    window.pywebview.api.gmail_disconnect().then(() => {
                        showToast("Gmail disconnected");
                        refreshSkills();
                    });
                });
            }

            $skillsList.appendChild(row);
        });
    });
}

window.onGmailAuthResult = function (result) {
    if (result && result.ok) {
        showToast("Gmail connected" + (result.email ? `: ${result.email}` : ""));
    } else {
        showToast("Gmail auth failed: " + (result && result.error ? result.error : "unknown"));
    }
    refreshSkills();
};

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
