/**
 * Expiry Tracker - Client Application
 * Version: 5.1 (Yellow Color Fixed & Robust)
 */

// ==========================================
// 1. CONFIGURATION
// ==========================================
const Config = {
    endpoints: {
        inventory:      '/api/inventory',
        categories:     '/api/categories',
        addItem:        '/api/add_item',
        deleteItem:     '/api/delete_item',
        addCategory:    '/api/add_category',
        deleteCategory: '/api/delete_category'
    },
    dom: {
        // Layout & Containers
        heroTitle:      'heroTitle',
        heroSub:        'heroSubtitle',
        sidebarList:    'categoryList',
        activityFeed:   'activityFeed',
        sidebar:        'appSidebar',
        hamburger:      'hamburgerBtn',
        
        // Metrics
        countSafe:      'countSafe',
        countUrgent:    'countUrgent',
        countExpired:   'countExpired',
        
        // Lists
        listAttention:  'attentionList',
        listStable:     'stableList',
        
        // UI Components
        viewBadge:      'currentViewBadge',
        categorySelect: 'itemCategory',
        
        // Modals
        modalItem:      'modalOverlay',
        modalCategory:  'catModalOverlay',
        
        // Inputs
        inputItemName:  'itemName',
        inputExpiry:    'expiryDate',
        inputCatName:   'newCatName',
        
        // Forms
        formAddItem:    'addItemForm',
        formAddCat:     'addCategoryForm'
    },
    icons: {
        'Food': '🍔', 'Medicine': '💊', 'Documents': '📄', 
        'Personal Care': '🧴', 'General': '📦', 'default': '📂'
    },
    settings: {
        urgentDays: 3, // FIXED: Matches the logic in _createViewModel
        maxLogEntries: 5,
        networkRetryCount: 1
    }
};

// ==========================================
// 2. STATE & UTILITIES
// ==========================================
const State = {
    isBusy: false,
    today: new Date(),
    rawData: null,
    activeCategory: 'All',
    categories: [],
    fetchController: null,
    lastFocusedEl: null
};

const Utils = {
    /** Calculates days remaining. Returns 999 if invalid. */
    getDaysRemaining(dateStr) {
        if (!dateStr) return 999;
        const target = new Date(dateStr);
        if (isNaN(target.getTime())) return 999;
        target.setHours(0, 0, 0, 0);
        // Calculate difference in days (ms per day = 86400000)
        return Math.ceil((target - State.today) / 86400000);
    },

    escape(text) {
        if (!text) return "";
        return String(text).replace(/[&<>"']/g, m => ({ 
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' 
        }[m]));
    },

    formatDate(dateStr) {
        try {
            return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        } catch { return 'Unknown'; }
    },

    setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }
};

// ==========================================
// 3. API LAYER
// ==========================================
const API = {
    async getWithRetry(endpoint, retries = Config.settings.networkRetryCount, signal = null) {
        try {
            const res = await fetch(endpoint, { signal });
            if (res.status === 401) { window.location.href = '/login'; return null; }
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return await res.json();
        } catch (err) {
            if (err.name === 'AbortError') throw err;
            if (retries > 0) {
                console.warn(`Retrying ${endpoint}...`);
                return this.getWithRetry(endpoint, retries - 1, signal);
            }
            console.error(`API Fail [${endpoint}]:`, err);
            return null;
        }
    },

    async post(endpoint, body) {
        try {
            const res = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Operation failed');
            return { success: true, data };
        } catch (err) {
            return { success: false, error: err.message };
        }
    }
};

// ==========================================
// 4. CORE LOGIC
// ==========================================
const Core = {
    init() {
        State.today.setHours(0, 0, 0, 0);
        UI.bindGlobalEvents();
        
        Promise.all([
            this.syncCategories(),
            this.syncInventory()
        ]).then(() => UI.log("System initialized."));
    },

    async syncCategories() {
        const data = await API.getWithRetry(Config.endpoints.categories);
        if (data?.categories) {
            State.categories = data.categories;
            requestAnimationFrame(() => {
                UI.renderSidebar();
                UI.renderDropdown();
            });
        }
    },

    async syncInventory() {
        if (State.fetchController) State.fetchController.abort();
        State.fetchController = new AbortController();

        try {
            const data = await API.getWithRetry(Config.endpoints.inventory, 1, State.fetchController.signal);
            if (data) {
                State.rawData = data;
                this.computeAndRender();
            } else {
                UI.setNetworkStatus('offline');
            }
        } catch (err) {
            if (err.name !== 'AbortError') UI.setNetworkStatus('offline');
        }
    },

    computeAndRender() {
        if (!State.rawData) return;

        const cat = State.activeCategory;
        const filterFn = item => cat === 'All' || item.category === cat;
        
        const rawFresh = (State.rawData.fresh || []).filter(filterFn);
        const rawExpired = (State.rawData.expired || []).filter(filterFn);

        const urgent = [];
        const safe = [];
        const expired = rawExpired.map(item => this._createViewModel(item, 'expired'));

        for (const item of rawFresh) {
            const model = this._createViewModel(item, 'fresh');
            if (model.status === 'urgent') urgent.push(model);
            else safe.push(model);
        }

        const sortFn = (a, b) => a.daysLeft - b.daysLeft;
        urgent.sort(sortFn);
        safe.sort(sortFn);

        requestAnimationFrame(() => UI.updateDashboard(safe, urgent, expired));
    },

    _createViewModel(item, type) {
        const days = Utils.getDaysRemaining(item.expiry_date);
        let status = 'safe';
        let label = 'SAFE';

        if (type === 'expired') {
            status = 'expired';
            label = 'EXPIRED';
        } else if (days <= Config.settings.urgentDays) { // This will now work correctly
            status = 'urgent';
            label = days <= 0 ? 'TODAY' : `${days} DAYS`;
        }

        return {
            ...item,
            daysLeft: days,
            status: status, 
            label: label,
            formattedDate: Utils.formatDate(item.expiry_date),
            safeName: Utils.escape(item.name),
            safeCat: Utils.escape(item.category || 'General')
        };
    }
};

// ==========================================
// 5. VIEW LAYER
// ==========================================
const UI = {
    renderSidebar() {
        const list = document.getElementById(Config.dom.sidebarList);
        if (!list) return;

        const fragment = document.createDocumentFragment();

        const createLi = (name, type, isActive) => {
            const li = document.createElement('li');
            li.className = isActive ? 'active' : '';
            li.dataset.category = name; 
            
            const icon = Config.icons[name] || Config.icons['default'];
            const safeName = Utils.escape(name);
            const delBtn = type === 'custom' 
                ? `<button class="btn-icon-del" data-action="delete-cat" data-name="${safeName}" title="Delete Folder">&times;</button>` 
                : '';

            li.innerHTML = `
                <div style="display:flex; align-items:center; flex:1; pointer-events:none;">
                    <span class="icon">${icon}</span> <span class="cat-name">${safeName}</span>
                </div>${delBtn}`;
            return li;
        };

        fragment.appendChild(createLi('All', 'system', State.activeCategory === 'All'));
        State.categories.forEach(cat => {
            fragment.appendChild(createLi(cat.name, cat.type, State.activeCategory === cat.name));
        });

        list.innerHTML = '';
        list.appendChild(fragment);
    },

    renderDropdown() {
        const select = document.getElementById(Config.dom.categorySelect);
        if (!select) return;
        select.innerHTML = State.categories
            .map(c => `<option value="${Utils.escape(c.name)}">${Utils.escape(c.name)}</option>`)
            .join('');
    },

    updateDashboard(safe, urgent, expired) {
        Utils.setText(Config.dom.countSafe, safe.length);
        Utils.setText(Config.dom.countUrgent, urgent.length);
        Utils.setText(Config.dom.countExpired, expired.length);

        this.setHeroState(urgent.length, expired.length);

        const badge = document.getElementById(Config.dom.viewBadge);
        if (badge) badge.textContent = State.activeCategory === 'All' ? 'All Items' : `Folder: ${State.activeCategory}`;

        this.renderList(Config.dom.listAttention, [...expired, ...urgent]);
        this.renderList(Config.dom.listStable, safe);
    },

    renderList(containerId, items) {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (items.length === 0) {
            container.innerHTML = `<div class="empty-message">No items found.</div>`;
            return;
        }

        const fragment = document.createDocumentFragment();

        items.forEach(vm => {
            const el = document.createElement('div');
            el.className = `item-card card-${vm.status}`;
            
            const jsSafeName = vm.safeName.replace(/'/g, "\\'");
            const actionHtml = vm.status === 'expired'
                ? `<span class="danger-warning">DO NOT USE</span>`
                : `<button class="btn-delete" data-action="delete-item" data-id="${vm.id}" data-name="${jsSafeName}" title="Remove">✕</button>`;

            el.innerHTML = `
                <div class="item-details">
                    <span class="item-name" title="${vm.safeName}">${vm.safeName}</span>
                    <div class="item-sub">
                        <span class="cat-pill">${vm.safeCat}</span>
                        <span class="item-meta">Expires ${vm.formattedDate}</span>
                    </div>
                </div>
                <div style="display:flex; align-items:center">
                    <span class="badge badge-${vm.status}">${vm.label}</span>
                    ${actionHtml}
                </div>`;
            fragment.appendChild(el);
        });

        container.innerHTML = '';
        container.appendChild(fragment);
    },

    setHeroState(urgentCount, expiredCount) {
        const title = document.getElementById(Config.dom.heroTitle);
        const sub = document.getElementById(Config.dom.heroSub);
        if (!title) return;

        if (expiredCount > 0 || urgentCount > 0) {
            title.textContent = "Attention Required";
            title.style.color = "var(--text-main)";
            sub.textContent = `${expiredCount} expired • ${urgentCount} expiring soon.`;
        } else {
            title.textContent = "Inventory Stable";
            title.style.color = "var(--safe)";
            sub.textContent = "No immediate risks detected.";
        }
    },

    setNetworkStatus(status) {
        const title = document.getElementById(Config.dom.heroTitle);
        if (title && status === 'offline') {
            title.textContent = "Offline / Error";
            title.style.color = "var(--danger)";
        }
    },

    toggleModal(modalId, show) {
        const el = document.getElementById(modalId);
        if (!el) return;

        if (show) {
            State.lastFocusedEl = document.activeElement; 
            el.classList.add('active');
            
            if (modalId === Config.dom.modalItem) {
                const dateIn = document.getElementById(Config.dom.inputExpiry);
                if (dateIn && !dateIn.value) dateIn.valueAsDate = new Date();
                setTimeout(() => document.getElementById(Config.dom.inputItemName)?.focus(), 100);
            } else {
                setTimeout(() => document.getElementById(Config.dom.inputCatName)?.focus(), 100);
            }
        } else {
            el.classList.remove('active');
            if (State.lastFocusedEl) State.lastFocusedEl.focus(); 
        }
    },

    log(msg) {
        const feed = document.getElementById(Config.dom.activityFeed);
        if (!feed) return;
        
        const time = new Date().toLocaleTimeString([], { hour12: false, hour:'2-digit', minute:'2-digit' });
        const div = document.createElement('div');
        div.className = 'log-entry';
        div.innerHTML = `<span class="log-time">${time}</span> <span>${Utils.escape(msg)}</span>`;
        
        feed.prepend(div);
        if (feed.children.length > Config.settings.maxLogEntries) feed.lastElementChild.remove();
    },

    bindGlobalEvents() {
        const bind = (id, event, fn) => document.getElementById(id)?.addEventListener(event, fn);

        bind('fabBtn', 'click', () => this.toggleModal(Config.dom.modalItem, true));
        bind(Config.dom.formAddItem, 'submit', Actions.submitItem);
        bind(Config.dom.formAddCat, 'submit', Actions.submitCategory);

        document.querySelectorAll('.close-modal').forEach(b => 
            b.addEventListener('click', e => this.toggleModal(e.target.closest('.modal-overlay').id, false)));
        
        document.querySelectorAll('.modal-overlay').forEach(o => 
            o.addEventListener('click', e => { if (e.target === o) this.toggleModal(o.id, false); }));

        document.addEventListener('click', e => {
            const sb = document.getElementById(Config.dom.sidebar);
            const ham = document.getElementById(Config.dom.hamburger);
            if (!sb) return;

            if (ham && ham.contains(e.target)) sb.classList.toggle('active');
            else if (sb.classList.contains('active') && !sb.contains(e.target) && !e.target.closest('#fabBtn')) {
                sb.classList.remove('active');
            }
        });

        document.getElementById(Config.dom.sidebarList)?.addEventListener('click', e => {
            const btn = e.target.closest('.btn-icon-del');
            const li = e.target.closest('li');

            if (btn) {
                e.stopPropagation();
                Actions.deleteCategory(btn.dataset.name);
            } else if (li) {
                Actions.setFilter(li.dataset.category);
            }
        });

        const handleInvClick = (e) => {
            const btn = e.target.closest('button[data-action="delete-item"]');
            if (btn) Actions.deleteItem(btn, btn.dataset.id, btn.dataset.name);
        };

        document.getElementById(Config.dom.listAttention)?.addEventListener('click', handleInvClick);
        document.getElementById(Config.dom.listStable)?.addEventListener('click', handleInvClick);
    }
};

// ==========================================
// 6. ACTIONS
// ==========================================
const Actions = {
    setFilter(category) {
        if (State.activeCategory === category) return;
        State.activeCategory = category;
        UI.renderSidebar();
        Core.computeAndRender();
        
        if (window.innerWidth <= 900) {
            document.getElementById(Config.dom.sidebar).classList.remove('active');
        }
    },

    async submitCategory(e) {
        e.preventDefault();
        const input = document.getElementById(Config.dom.inputCatName);
        const name = input.value.trim();
        if (!name) return;

        const res = await API.post(Config.endpoints.addCategory, { name });
        if (res.success) {
            UI.log(`Folder created: ${name}`);
            input.value = '';
            UI.toggleModal(Config.dom.modalCategory, false);
            Core.syncCategories();
        } else {
            alert(res.error);
        }
    },

    async deleteCategory(name) {
        if (!confirm(`Delete "${name}"? Items inside will move to General.`)) return;

        const res = await API.post(Config.endpoints.deleteCategory, { name });
        if (res.success) {
            if (State.activeCategory === name) State.activeCategory = 'All';
            UI.log(`Deleted folder: ${name}`);
            await Core.syncCategories();
            Core.syncInventory(); 
        } else {
            alert("Delete failed.");
        }
    },

    async submitItem(e) {
        e.preventDefault();
        if (State.isBusy) return;

        const els = {
            name: document.getElementById(Config.dom.inputItemName),
            date: document.getElementById(Config.dom.inputExpiry),
            cat: document.getElementById(Config.dom.categorySelect),
            btn: e.target.querySelector('button')
        };

        if (!els.name.value.trim() || !els.date.value) return;

        State.isBusy = true;
        els.btn.disabled = true;
        els.btn.textContent = "Saving...";

        const payload = { 
            name: els.name.value.trim(), 
            expiry_date: els.date.value, 
            category: els.cat.value 
        };

        const res = await API.post(Config.endpoints.addItem, payload);
        
        if (res.success) {
            UI.toggleModal(Config.dom.modalItem, false);
            els.name.value = '';
            UI.log(`Added: ${payload.name}`);
            Core.syncInventory();
        } else {
            alert("Failed to add item.");
        }

        State.isBusy = false;
        els.btn.disabled = false;
        els.btn.textContent = "Add to Inventory";
    },

    async deleteItem(btn, id, name) {
        if (State.isBusy) return;
        if (!confirm(`Delete "${name}"?`)) return;

        State.isBusy = true;
        btn.style.opacity = "0.5";

        const res = await API.post(Config.endpoints.deleteItem, { id: parseInt(id) });
        if (res.success) {
            UI.log(`Deleted: ${name}`);
            Core.syncInventory();
        } else {
            btn.style.opacity = "1";
            alert("Delete failed.");
        }
        State.isBusy = false;
    }
};

window.App = {
    openCategoryModal: () => UI.toggleModal(Config.dom.modalCategory, true),
    closeCategoryModal: () => UI.toggleModal(Config.dom.modalCategory, false)
};

document.addEventListener('DOMContentLoaded', () => Core.init());