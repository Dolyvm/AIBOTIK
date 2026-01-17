const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

// Get user_id from URL or Telegram
const urlParams = new URLSearchParams(window.location.search);
const userId = tg.initDataUnsafe?.user?.id || urlParams.get('user_id');

let currentTab = 'characters';
let filters = { genre: null, style: null };

// === Navigation ===
document.querySelectorAll('#bottom-nav button').forEach(btn => {
    btn.addEventListener('click', () => {
        currentTab = btn.dataset.tab;
        document.querySelectorAll('#bottom-nav button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderTab(currentTab);
    });
});

// === Modal Controls ===
document.querySelector('.modal-close').addEventListener('click', () => {
    document.getElementById('modal').classList.add('hidden');
});

document.getElementById('modal').addEventListener('click', (e) => {
    if (e.target.id === 'modal') {
        document.getElementById('modal').classList.add('hidden');
    }
});

// === Filter Controls ===
window.setFilter = function(type, value) {
    filters[type] = value || null;
    renderTab('characters');
};

// === Render Tabs ===
async function renderTab(tab) {
    const content = document.getElementById('content');

    switch(tab) {
        case 'characters':
            content.innerHTML = await renderCharacters();
            break;
        case 'worlds':
            content.innerHTML = await renderWorlds();
            break;
        case 'chats':
            content.innerHTML = await renderChats();
            break;
        case 'create':
            content.innerHTML = renderCreateStub();
            break;
        case 'profile':
            content.innerHTML = await renderProfile();
            break;
    }
}

// === Characters Tab ===
async function renderCharacters() {
    try {
        const filterOptions = await fetch('/api/characters/filters/options').then(r => r.json());
        const params = new URLSearchParams();
        if (filters.genre) params.set('genre', filters.genre);
        if (filters.style) params.set('style', filters.style);

        const data = await fetch(`/api/characters?${params}`).then(r => r.json());

        return `
            <div class="filters">
                <select id="filter-genre" onchange="setFilter('genre', this.value)">
                    <option value="">Все жанры</option>
                    ${filterOptions.genres.map(g => `<option value="${g}" ${filters.genre === g ? 'selected' : ''}>${g}</option>`).join('')}
                </select>
                <select id="filter-style" onchange="setFilter('style', this.value)">
                    <option value="">Все стили</option>
                    ${filterOptions.styles.map(s => `<option value="${s}" ${filters.style === s ? 'selected' : ''}>${s}</option>`).join('')}
                </select>
            </div>
            <div class="characters-grid">
                ${data.characters.map(char => `
                    <div class="character-card" onclick="openCharacterModal('${char.id}')">
                        <img src="${char.avatar}" alt="${char.name}">
                        <div class="card-overlay">
                            <span class="card-name">${char.name}</span>
                        </div>
                        ${char.tags.some(t => ['Erotic', 'Taboo', 'Dominant'].includes(t)) ? '<span class="nsfw-badge">🔥</span>' : ''}
                    </div>
                `).join('')}
            </div>
        `;
    } catch (error) {
        return `<div class="empty-state">Ошибка загрузки персонажей: ${error.message}</div>`;
    }
}

// === Character Modal ===
window.openCharacterModal = async function(charId) {
    try {
        const char = await fetch(`/api/characters/${charId}`).then(r => r.json());

        document.getElementById('modal-body').innerHTML = `
            <img src="${char.avatar}" class="modal-image">
            <h2>${char.name}</h2>
            <p>${char.description}</p>
            <div class="tags">${char.tags.map(t => `<span class="tag">${t}</span>`).join('')}</div>

            <h3>Выбери сценарий:</h3>
            <div class="scenarios">
                ${char.scenarios.map(s => `
                    <button class="scenario-btn" onclick="startChat('character', '${charId}', ${s.index})">
                        <strong>${s.name}</strong>
                        <small>${s.preview}</small>
                    </button>
                `).join('')}
            </div>
        `;

        document.getElementById('modal').classList.remove('hidden');
    } catch (error) {
        alert('Ошибка загрузки персонажа');
    }
};

// === Start Chat ===
window.startChat = function(type, id, scenarioIndex) {
    const data = {
        action: 'start_chat',
        type: type,
        id: id,
        scenario: scenarioIndex
    };

    tg.sendData(JSON.stringify(data));
    tg.close();
};

// === Worlds Tab ===
let worldFilters = { genre: null, rating: null };

window.setWorldFilter = function(type, value) {
    worldFilters[type] = value || null;
    renderTab('worlds');
};

async function renderWorlds() {
    try {
        // Get unique genres and ratings
        const allWorlds = await fetch('/api/worlds').then(r => r.json());

        const params = new URLSearchParams();
        if (worldFilters.genre) params.set('genre', worldFilters.genre);
        if (worldFilters.rating) params.set('rating', worldFilters.rating);

        const data = await fetch(`/api/worlds?${params}`).then(r => r.json());

        // Extract unique genres and ratings for filters
        const genres = [...new Set(allWorlds.worlds.map(w => w.tags).flat())];
        const ratings = ['PG-13', 'R', 'NC-17']; // Common ratings

        if (data.worlds.length === 0 && (worldFilters.genre || worldFilters.rating)) {
            return `
                <div class="filters">
                    <select id="filter-world-genre" onchange="setWorldFilter('genre', this.value)">
                        <option value="">Все жанры</option>
                        ${genres.map(g => `<option value="${g}" ${worldFilters.genre === g ? 'selected' : ''}>${g}</option>`).join('')}
                    </select>
                    <select id="filter-world-rating" onchange="setWorldFilter('rating', this.value)">
                        <option value="">Все рейтинги</option>
                        ${ratings.map(r => `<option value="${r}" ${worldFilters.rating === r ? 'selected' : ''}>${r}</option>`).join('')}
                    </select>
                </div>
                <div class="empty-state">Нет миров с такими фильтрами</div>
            `;
        }

        if (allWorlds.worlds.length === 0) {
            return '<div class="empty-state">Миры пока не добавлены</div>';
        }

        return `
            <div class="filters">
                <select id="filter-world-genre" onchange="setWorldFilter('genre', this.value)">
                    <option value="">Все жанры</option>
                    ${genres.map(g => `<option value="${g}" ${worldFilters.genre === g ? 'selected' : ''}>${g}</option>`).join('')}
                </select>
                <select id="filter-world-rating" onchange="setWorldFilter('rating', this.value)">
                    <option value="">Все рейтинги</option>
                    ${ratings.map(r => `<option value="${r}" ${worldFilters.rating === r ? 'selected' : ''}>${r}</option>`).join('')}
                </select>
            </div>
            <div class="characters-grid">
                ${data.worlds.map(world => `
                    <div class="character-card" onclick="openWorldModal('${world.id}')">
                        <img src="${world.cover_image}" alt="${world.name}">
                        <div class="card-overlay">
                            <span class="card-name">${world.name}</span>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    } catch (error) {
        return `<div class="empty-state">Ошибка загрузки миров: ${error.message}</div>`;
    }
}

window.openWorldModal = async function(worldId) {
    try {
        const world = await fetch(`/api/worlds/${worldId}`).then(r => r.json());

        document.getElementById('modal-body').innerHTML = `
            <img src="${world.cover_image}" class="modal-image">
            <h2>${world.name}</h2>
            <p>${world.description}</p>
            <div class="tags">${world.tags.map(t => `<span class="tag">${t}</span>`).join('')}</div>

            <button class="scenario-btn" onclick="startChat('world', '${worldId}', 0)">
                <strong>Начать приключение</strong>
            </button>
        `;

        document.getElementById('modal').classList.remove('hidden');
    } catch (error) {
        alert('Ошибка загрузки мира');
    }
};

// === Chats Tab ===
async function renderChats() {
    if (!userId) {
        return '<div class="empty-state">Пользователь не найден</div>';
    }

    try {
        const data = await fetch(`/api/user/${userId}/chats`).then(r => r.json());

        if (data.chats.length === 0) {
            return '<div class="empty-state">У вас пока нет чатов. Выберите персонажа или мир!</div>';
        }

        return `
            <div class="chats-list">
                ${data.chats.map(chat => `
                    <div class="chat-item" onclick="continueChat(${chat.id})">
                        ${chat.avatar ? `<img src="${chat.avatar}" class="chat-avatar">` : ''}
                        <div class="chat-info">
                            <h4>${chat.type === 'character' ? '👤' : '🌍'} ${chat.name}</h4>
                            <small>Обновлено: ${new Date(chat.updated_at).toLocaleString('ru')}</small>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    } catch (error) {
        return `<div class="empty-state">Ошибка загрузки чатов: ${error.message}</div>`;
    }
}

// === Create Tab (Stub) ===
function renderCreateStub() {
    return `
        <div class="create-wizard">
            <h2>✨ Создай своего персонажа</h2>

            <div class="step">
                <h3>Шаг 1: Пол</h3>
                <div class="options">
                    <button class="option-btn selected">♀️ Женский</button>
                    <button class="option-btn">♂️ Мужской</button>
                    <button class="option-btn">⚧ Небинарный</button>
                </div>
            </div>

            <div class="step">
                <h3>Шаг 2: Внешность</h3>
                <div class="appearance-grid">
                    <div class="appearance-option">
                        <label>Волосы</label>
                        <div class="icons">
                            <span class="icon selected">💇‍♀️</span>
                            <span class="icon">👩‍🦰</span>
                            <span class="icon">👩‍🦱</span>
                        </div>
                    </div>
                    <div class="appearance-option">
                        <label>Телосложение</label>
                        <div class="icons">
                            <span class="icon">🧍‍♀️</span>
                            <span class="icon selected">💃</span>
                            <span class="icon">🏋️‍♀️</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="step">
                <h3>Шаг 3: Характер</h3>
                <input type="text" placeholder="Опиши характер..." class="text-input">
            </div>

            <div class="step">
                <h3>Шаг 4: Ограничения</h3>
                <div class="checkboxes">
                    <label><input type="checkbox"> Без насилия</label>
                    <label><input type="checkbox"> Без табу-тем</label>
                </div>
            </div>

            <button class="primary-btn" onclick="alert('🚧 Функция в разработке')">
                Создать персонажа
            </button>
        </div>
    `;
}

// === Profile Tab ===
async function renderProfile() {
    if (!userId) {
        return '<div class="empty-state">Пользователь не найден</div>';
    }

    try {
        const user = await fetch(`/api/user/${userId}`).then(r => r.json());
        const avatar = user.avatar_url || '😍';

        return `
            <div class="profile">
                <div class="avatar">${avatar.startsWith('http') ? `<img src="${avatar}">` : avatar}</div>
                <h2>${user.username || 'Пользователь'}</h2>
                <p class="user-id">ID: ${user.telegram_id}</p>

                <div class="balance-card">
                    <span class="balance-label">Баланс</span>
                    <span class="balance-value">${user.balance} 💎</span>
                </div>

                <div class="settings">
                    <div class="setting-row">
                        <span>Скрывать NSFW</span>
                        <label class="toggle">
                            <input type="checkbox" ${user.nsfw_blur ? 'checked' : ''} disabled>
                            <span class="slider"></span>
                        </label>
                    </div>
                </div>

                <div class="subscription-plans">
                    <h3>Планы подписки</h3>
                    <div class="plans-grid">
                        <div class="plan">
                            <h4>Базовый</h4>
                            <p>150 токенов/мес</p>
                            <span class="price">Бесплатно</span>
                        </div>
                        <div class="plan featured">
                            <h4>Премиум</h4>
                            <p>1000 токенов/мес</p>
                            <span class="price">$9.99</span>
                            <button disabled>Скоро</button>
                        </div>
                        <div class="plan">
                            <h4>Безлимит</h4>
                            <p>∞ токенов</p>
                            <span class="price">$29.99</span>
                            <button disabled>Скоро</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    } catch (error) {
        return `<div class="empty-state">Ошибка загрузки профиля: ${error.message}</div>`;
    }
}

// === Continue Chat ===
window.continueChat = async function(chatId) {
    // For now, just inform the user
    // In production, this would activate the chat and close WebApp
    alert(`Чат #${chatId} активирован. Вернитесь в Telegram для продолжения.`);
    tg.close();
};

// === Initialize ===
renderTab('characters');
