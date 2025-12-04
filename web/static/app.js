// Initialize Telegram WebApp
const tg = window.Telegram.WebApp;
tg.expand();

// State
let currentCharacter = null;
let characters = [];
let scenarios = [];
let userStatus = null;

// DOM Elements
const characterView = document.getElementById('character-view');
const scenarioView = document.getElementById('scenario-view');
const statusView = document.getElementById('status-view');
const charactersGrid = document.getElementById('characters-grid');
const scenariosList = document.getElementById('scenarios-list');
const statusContent = document.getElementById('status-content');
const loading = document.getElementById('loading');
const backBtn = document.getElementById('back-btn');
const statusBackBtn = document.getElementById('status-back-btn');
const navCharacters = document.getElementById('nav-characters');
const navStatus = document.getElementById('nav-status');
const characterNameEl = document.getElementById('character-name');
const scenarioModal = document.getElementById('scenario-modal');
const modalClose = document.getElementById('modal-close');
const modalTitle = document.getElementById('modal-title');
const modalText = document.getElementById('modal-text');
const modalStart = document.getElementById('modal-start');

// API Base URL
const API_URL = window.location.origin;

// Utility Functions
function showLoading() {
    loading.classList.remove('hidden');
}

function hideLoading() {
    loading.classList.add('hidden');
}

function showView(viewName) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));

    if (viewName === 'characters') {
        characterView.classList.add('active');
        navCharacters.classList.add('active');
    } else if (viewName === 'scenarios') {
        scenarioView.classList.add('active');
    } else if (viewName === 'status') {
        statusView.classList.add('active');
        navStatus.classList.add('active');
        loadStatus();
    }
}

async function fetchAPI(endpoint) {
    const response = await fetch(`${API_URL}${endpoint}`);
    if (!response.ok) {
        throw new Error(`API request failed: ${response.statusText}`);
    }
    return await response.json();
}

// Load Characters
async function loadCharacters() {
    showLoading();
    try {
        const data = await fetchAPI('/api/characters');
        characters = data.characters;
        renderCharacters();
    } catch (error) {
        console.error('Failed to load characters:', error);
        tg.showAlert('Ошибка загрузки персонажей');
    } finally {
        hideLoading();
    }
}

function renderCharacters() {
    charactersGrid.innerHTML = '';

    characters.forEach(char => {
        const card = document.createElement('div');
        card.className = 'character-card';
        card.innerHTML = `
            <img src="${char.image}" alt="${char.name}" onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22200%22 height=%22200%22%3E%3Crect fill=%22%23ddd%22 width=%22200%22 height=%22200%22/%3E%3C/svg%3E'">
            <div class="character-name">${char.name}</div>
            <div class="character-scenarios">${char.total_greetings} ${char.total_greetings === 1 ? 'сценарий' : 'сценария'}</div>
        `;
        card.addEventListener('click', () => selectCharacter(char));
        charactersGrid.appendChild(card);
    });
}

// Select Character
async function selectCharacter(char) {
    currentCharacter = char;
    characterNameEl.textContent = char.name;

    showLoading();
    try {
        const data = await fetchAPI(`/api/characters/${char.id}/scenarios`);
        scenarios = data.scenarios;
        renderScenarios();
        showView('scenarios');
    } catch (error) {
        console.error('Failed to load scenarios:', error);
        tg.showAlert('Ошибка загрузки сценариев');
    } finally {
        hideLoading();
    }
}

function renderScenarios() {
    scenariosList.innerHTML = '';

    scenarios.forEach(scenario => {
        const item = document.createElement('div');
        item.className = 'scenario-item';
        item.innerHTML = `
            <div class="scenario-header">
                <span class="scenario-name">${scenario.name}</span>
            </div>
            <div class="scenario-preview">${scenario.preview}</div>
        `;
        item.addEventListener('click', () => selectScenario(scenario));
        scenariosList.appendChild(item);
    });
}

// Select Scenario - show modal with full text
async function selectScenario(scenario) {
    modalTitle.textContent = scenario.name;

    // Load full greeting text
    showLoading();
    try {
        const response = await fetchAPI(`/api/characters/${currentCharacter.id}/scenarios/${scenario.index}/full`);
        modalText.textContent = response.text;

        // Store scenario data for the start button
        modalStart.dataset.characterId = currentCharacter.id;
        modalStart.dataset.scenarioIndex = scenario.index;

        // Show modal
        scenarioModal.classList.remove('hidden');
    } catch (error) {
        console.error('Failed to load full greeting:', error);
        tg.showAlert('Ошибка загрузки текста сценария');
    } finally {
        hideLoading();
    }
}

// Close modal
function closeModal() {
    scenarioModal.classList.add('hidden');
}

// Start chat from modal
function startChat() {
    const data = {
        character_id: modalStart.dataset.characterId,
        scenario_index: parseInt(modalStart.dataset.scenarioIndex)
    };

    // Send data to bot and close WebApp
    tg.sendData(JSON.stringify(data));
    tg.close();
}

// Load Status
async function loadStatus() {
    // Детальное логирование для отладки
    console.log('=== DEBUG: loadStatus called ===');
    console.log('tg object:', tg);
    console.log('tg.initDataUnsafe:', tg.initDataUnsafe);
    console.log('tg.initData:', tg.initData);
    console.log('tg.platform:', tg.platform);
    console.log('tg.version:', tg.version);

    // Попытка получить user_id разными способами
    let userId = null;

    // Способ 1: через initDataUnsafe.user
    if (tg.initDataUnsafe && tg.initDataUnsafe.user) {
        userId = tg.initDataUnsafe.user.id;
        console.log('✓ Got user_id from initDataUnsafe.user:', userId);
    }

    // Способ 2: попробовать распарсить initData вручную
    if (!userId && tg.initData) {
        console.log('Trying to parse initData manually...');
        try {
            const params = new URLSearchParams(tg.initData);
            const userStr = params.get('user');
            if (userStr) {
                const user = JSON.parse(decodeURIComponent(userStr));
                userId = user.id;
                console.log('✓ Got user_id from initData parsing:', userId);
            }
        } catch (e) {
            console.error('Failed to parse initData:', e);
        }
    }

    // Способ 3: получить из URL параметров (fallback)
    if (!userId) {
        console.log('Trying to get user_id from URL params...');
        const urlParams = new URLSearchParams(window.location.search);
        const userIdParam = urlParams.get('user_id');
        if (userIdParam) {
            userId = parseInt(userIdParam);
            console.log('✓ Got user_id from URL params:', userId);
        }
    }

    // Если все еще нет userId - показываем детальную ошибку
    if (!userId) {
        console.error('✗ Failed to get user_id from any method');
        statusContent.innerHTML = `
            <div class="error">
                <p style="font-weight: bold; margin-bottom: 10px;">Не удалось получить данные пользователя</p>
                <div style="font-size: 12px; text-align: left; background: rgba(0,0,0,0.1); padding: 10px; border-radius: 8px;">
                    <p><strong>Debug Info:</strong></p>
                    <p>Platform: ${tg.platform || 'unknown'}</p>
                    <p>Version: ${tg.version || 'unknown'}</p>
                    <p>initDataUnsafe: ${tg.initDataUnsafe ? 'present' : 'missing'}</p>
                    <p>initData: ${tg.initData ? 'present (length: ' + tg.initData.length + ')' : 'missing'}</p>
                    <p>user in initDataUnsafe: ${tg.initDataUnsafe?.user ? 'yes' : 'no'}</p>
                </div>
                <p style="font-size: 12px; color: #7f8c8d; margin-top: 10px;">
                    WebApp должен быть открыт из Telegram через кнопку "Меню"
                </p>
            </div>
        `;
        return;
    }

    console.log('Fetching status for user_id:', userId);

    showLoading();
    try {
        const data = await fetchAPI(`/api/status/${userId}`);
        userStatus = data;
        renderStatus();
    } catch (error) {
        console.error('Failed to load status:', error);
        statusContent.innerHTML = `
            <p class="error">Ошибка загрузки статуса</p>
            <p style="font-size: 12px; color: #7f8c8d; margin-top: 10px;">
                ${error.message || 'Неизвестная ошибка'}
            </p>
        `;
    } finally {
        hideLoading();
    }
}

function renderStatus() {
    if (!userStatus) {
        statusContent.innerHTML = '<p>Нет данных</p>';
        return;
    }

    const state = userStatus.state;

    statusContent.innerHTML = `
        <div class="status-section">
            <h2>Текущий персонаж</h2>
            <p class="status-character">${userStatus.character_name}</p>
            <p class="status-detail">Сценарий: ${userStatus.scenario_index === 0 ? 'Основной' : `Альтернативный ${userStatus.scenario_index}`}</p>
        </div>

        <div class="status-section">
            <h2>Статистика отношений</h2>
            <div class="stat-item">
                <span class="stat-label">📊 Доверие</span>
                <div class="stat-bar">
                    <div class="stat-fill" style="width: ${state.trust}%"></div>
                    <span class="stat-value">${state.trust}/100</span>
                </div>
            </div>
            <div class="stat-item">
                <span class="stat-label">💕 Привязанность</span>
                <div class="stat-bar">
                    <div class="stat-fill" style="width: ${state.affection}%"></div>
                    <span class="stat-value">${state.affection}/100</span>
                </div>
            </div>
            <div class="stat-item">
                <span class="stat-label">🔥 Возбуждение</span>
                <div class="stat-bar">
                    <div class="stat-fill" style="width: ${state.arousal}%"></div>
                    <span class="stat-value">${state.arousal}/100</span>
                </div>
            </div>
            <div class="stat-item">
                <span class="stat-label">😌 Комфорт</span>
                <div class="stat-bar">
                    <div class="stat-fill" style="width: ${state.comfort}%"></div>
                    <span class="stat-value">${state.comfort}/100</span>
                </div>
            </div>
        </div>

        <div class="status-section">
            <h2>Состояние</h2>
            <p class="status-detail">📈 Стадия отношений: <strong>${state.relationship_stage}</strong></p>
            <p class="status-detail">😊 Настроение: <strong>${state.mood}</strong></p>
            <p class="status-detail">💬 Всего сообщений: <strong>${userStatus.message_count}</strong></p>
        </div>
    `;
}

// Event Listeners
backBtn.addEventListener('click', () => showView('characters'));
statusBackBtn.addEventListener('click', () => showView('characters'));
navCharacters.addEventListener('click', () => showView('characters'));
navStatus.addEventListener('click', () => showView('status'));
modalClose.addEventListener('click', closeModal);
modalStart.addEventListener('click', startChat);

// Close modal on background click
scenarioModal.addEventListener('click', (e) => {
    if (e.target === scenarioModal) {
        closeModal();
    }
});

// Initialize
console.log('=== WebApp Initialization ===');
console.log('Telegram WebApp object:', tg);
console.log('Is WebApp ready:', tg.isVersionAtLeast('6.0'));
console.log('initDataUnsafe:', tg.initDataUnsafe);
console.log('initData (raw):', tg.initData);

loadCharacters();

// Set theme colors
tg.setHeaderColor('#2c3e50');
tg.setBackgroundColor('#ecf0f1');

// Делаем WebApp видимым и расширяем на весь экран
tg.ready();
tg.expand();
