document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const qForm = document.getElementById('questionnaire-form');
    const qFields = document.getElementById('questionnaire-fields');
    const loadingView = document.getElementById('loading-view');
    const formView = document.getElementById('form-view');
    const resultsView = document.getElementById('results-view');
    const errorView = document.getElementById('error-view');
    const errorMessage = document.getElementById('error-message');
    const submitBtn = document.getElementById('submit-btn');
    const btnText = document.getElementById('btn-text');
    const btnSpinner = document.getElementById('btn-spinner');
    const restartBtn = document.getElementById('restart-btn');

    // Welcome Screen Elements
    const welcomeView = document.getElementById('welcome-view');
    const resumeForm = document.getElementById('resume-form');
    const resumeIdInput = document.getElementById('resume-id');
    const resumeError = document.getElementById('resume-error');
    const startFreshBtn = document.getElementById('start-fresh-btn');

    // Questionnaire Form Elements
    const activeSessionBanner = document.getElementById('active-session-banner');
    const activePortIdDisplay = document.getElementById('active-port-id');

    // Results Elements
    const scoreVal = document.getElementById('score-val');
    const recList = document.getElementById('recommendations-list');
    const displayPortId = document.getElementById('display-port-id');
    const decisionSummaryText = document.getElementById('decision-summary-text');
    const decisionFilters = document.getElementById('decision-filters');

    // Global session state
    let currentPortfolioId = null;

    // Initialize Application
    loadQuestionnaire();

    // Event Listeners
    qForm.addEventListener('submit', handleSubmission);
    restartBtn.addEventListener('click', resetApp);
    startFreshBtn.addEventListener('click', () => {
        currentPortfolioId = null;
        qForm.reset();
        clearResults();
        showFormView(null);
    });
    resumeForm.addEventListener('submit', handleResume);

    // Core Functions
    async function loadQuestionnaire() {
        try {
            const response = await fetch('/api/questionnaire');
            if (!response.ok) throw new Error('Failed to load questionnaire schema');

            const data = await response.json();
            renderForm(data.sections || []);

            loadingView.classList.add('hidden');
            welcomeView.classList.remove('hidden');
        } catch (err) {
            showError("Could not connect to server to load the questionnaire.");
            console.error(err);
        }
    }

    function renderForm(sections) {
        qFields.innerHTML = '';

        sections.forEach((section) => {
            const group = document.createElement('div');
            group.className = 'form-group';

            const label = document.createElement('label');
            label.htmlFor = section.id;
            label.textContent = section.title || section.id.replace('_', ' ').toUpperCase();

            if (section.required) {
                const reqSpan = document.createElement('span');
                reqSpan.textContent = ' *';
                reqSpan.style.color = 'var(--accent)';
                label.appendChild(reqSpan);
            }

            group.appendChild(label);

            if (section.description) {
                const desc = document.createElement('p');
                desc.style.fontSize = '0.85rem';
                desc.style.color = 'var(--text-secondary)';
                desc.style.marginBottom = '0.5rem';
                desc.textContent = section.description;
                group.appendChild(desc);
            }

            if (section.type === 'single_select') {
                const wrapper = document.createElement('div');
                wrapper.className = 'select-wrapper';

                const select = document.createElement('select');
                select.id = section.id;
                select.name = section.id;
                if (section.required) select.required = true;

                const defaultOpt = document.createElement('option');
                defaultOpt.value = '';
                defaultOpt.textContent = 'Select an option...';
                defaultOpt.disabled = true;
                defaultOpt.selected = true;
                select.appendChild(defaultOpt);

                (section.options || []).forEach(opt => {
                    const option = document.createElement('option');
                    option.value = opt.value;
                    option.textContent = opt.label;
                    select.appendChild(option);
                });

                wrapper.appendChild(select);
                group.appendChild(wrapper);
            } else if (section.type === 'multi_select') {
                const wrapper = document.createElement('div');
                wrapper.className = 'checkbox-wrapper';
                wrapper.style.display = 'flex';
                wrapper.style.flexDirection = 'column';
                wrapper.style.gap = '0.5rem';
                wrapper.style.marginTop = '0.5rem';

                (section.options || []).forEach(opt => {
                    const cbLabel = document.createElement('label');
                    cbLabel.style.display = 'flex';
                    cbLabel.style.alignItems = 'center';
                    cbLabel.style.fontWeight = 'normal';
                    cbLabel.style.cursor = 'pointer';
                    cbLabel.style.marginBottom = '0';
                    cbLabel.style.color = 'var(--text-primary)';

                    const cb = document.createElement('input');
                    cb.type = 'checkbox';
                    cb.name = section.id;
                    cb.value = opt.value;
                    cb.style.marginRight = '0.75rem';
                    cb.style.width = 'auto'; // override default CSS width:100%

                    cbLabel.appendChild(cb);
                    cbLabel.appendChild(document.createTextNode(opt.label));
                    wrapper.appendChild(cbLabel);
                });

                group.appendChild(wrapper);
            } else {
                // Fallback for unexpected types
                const input = document.createElement('input');
                input.type = 'text';
                input.id = section.id;
                input.name = section.id;
                if (section.required) input.required = true;
                group.appendChild(input);
            }

            qFields.appendChild(group);
        });
    }

    async function handleSubmission(e) {
        e.preventDefault();

        // Hide errors, show spinner
        errorView.classList.add('hidden');
        clearResults();
        setLoadingState(true);

        const formData = new FormData(qForm);
        const userAnswers = {};

        for (const [key, value] of formData.entries()) {
            if (userAnswers[key]) {
                if (!Array.isArray(userAnswers[key])) {
                    userAnswers[key] = [userAnswers[key]];
                }
                userAnswers[key].push(value);
            } else {
                // Check if this was supposed to be a multi_select but only 1 option was checked
                const checkboxesForName = qForm.querySelectorAll(`input[type="checkbox"][name="${key}"]`);
                if (checkboxesForName.length > 0) {
                    userAnswers[key] = [value];
                } else {
                    userAnswers[key] = value;
                }
            }
        }

        const payload = { user_answers: userAnswers };
        if (currentPortfolioId) {
            payload.portfolio_id = currentPortfolioId;
        }

        console.log("Submitting payload to /api/portfolio:", payload);

        try {
            const response = await fetch('/api/portfolio', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json();

            if (!response.ok) {
                const details = data.details && data.details.length ? `\nReason: ${data.details.join('; ')}` : '';
                throw new Error((data.error || 'Failed to generate portfolio') + details);
            }

            displayResults(data);

        } catch (err) {
            showError(err.message);
            setLoadingState(false);
        }
    }

    function displayResults(portfolio) {
        setLoadingState(false);
        formView.classList.add('hidden');
        resultsView.classList.remove('hidden');

        // Display Portfolio ID
        if (displayPortId) {
            displayPortId.textContent = portfolio.portfolio_id || 'Unknown ID';
        }

        // Remove any previous warnings
        const previousWarnings = resultsView.querySelectorAll('.alert-error');
        previousWarnings.forEach(w => w.remove());

        // Risk profile display
        const riskLabel = portfolio.risk_profile || portfolio.user_answers?.risk_approach || 'Unknown';
        scoreVal.textContent = riskLabel.replace('_', ' ').toUpperCase();

        // Decision summary
        if (decisionSummaryText) {
            const summary = portfolio.explanations?.summary || 'Summary unavailable.';
            decisionSummaryText.textContent = summary;
        }

        if (decisionFilters) {
            decisionFilters.innerHTML = '';
            const filters = portfolio.decision_trace?.filters || [];
            filters.forEach((f) => {
                const pill = document.createElement('span');
                pill.className = 'decision-filter';
                pill.textContent = `${f.name}: ${f.before}→${f.after}`;
                decisionFilters.appendChild(pill);
            });

            const relaxations = portfolio.decision_trace?.relaxations || [];
            const relaxationLabels = {
                risk_band_relaxation: 'risk band relaxed',
                final_fund_floor: 'risk filter dropped'
            };
            relaxations.forEach((r) => {
                const pill = document.createElement('span');
                pill.className = 'decision-filter';
                const label = relaxationLabels[r.name] || r.name;
                pill.textContent = `relaxation: ${label} ${r.before}→${r.after}`;
                decisionFilters.appendChild(pill);
            });
        }

        // Add transparency warning if default fallback was used
        const usedFallback = portfolio.decision_trace?.used_fallback_risk || false;
        if (usedFallback) {
            const warningEl = document.createElement('div');
            warningEl.className = 'alert alert-error';
            warningEl.style.marginBottom = '1.5rem';
            warningEl.style.color = '#ff7b72';
            warningEl.style.backgroundColor = 'rgba(248, 81, 73, 0.1)';
            warningEl.style.border = '1px solid rgba(248, 81, 73, 0.4)';
            warningEl.innerHTML = '<strong>Note:</strong> We could not strongly determine your exact risk profile from the provided answers. The engine defaulted to a <strong>Balanced</strong> risk profile.';

            // Insert after results header
            const header = resultsView.querySelector('.results-header');
            header.parentNode.insertBefore(warningEl, header.nextSibling);
        }

        if (!portfolio.recommendations || !portfolio.recommendations.length) {
            recList.innerHTML = '<p style="color:var(--text-secondary)">No valid recommendations available.</p>';
            return;
        }

        recList.innerHTML = '';

        portfolio.recommendations.forEach(rec => {
            const item = document.createElement('div');
            item.className = 'fund-item form-group'; // Reuse animation class

            const isinLabel = rec.isin ? `<span class="badge ${rec.asset_class?.toLowerCase() || 'bond'}">${rec.asset_class || 'BOND'}</span>` : '';
            const explanations = Array.isArray(rec.explanations) ? rec.explanations : [];
            const explanationsHtml = explanations.length
                ? `<ul class="fund-explanations">${explanations.map(e => `<li>${e}</li>`).join('')}</ul>`
                : '';

            item.innerHTML = `
                <div class="fund-meta">
                    <h4>${rec.name || 'Unknown Fund'} ${isinLabel}</h4>
                    <p>${rec.isin || 'N/A'} • Exp. Ratio: ${(rec.yearly_fee || 0).toFixed(2)}%</p>
                    <p style="font-size: 0.8rem; margin-top: 0.5rem">${rec.rationale || ''}</p>
                    ${explanationsHtml}
                </div>
                <div class="fund-allocation">
                    <div class="allocation-percent">${(rec.allocation_percent || 0).toFixed(2)}%</div>
                    <div class="allocation-label">Target Weight</div>
                </div>
            `;

            recList.appendChild(item);
        });
    }

    function clearResults() {
        resultsView.classList.add('hidden');
        if (displayPortId) displayPortId.textContent = '';
        if (scoreVal) scoreVal.textContent = '';
        if (decisionSummaryText) decisionSummaryText.textContent = '';
        if (decisionFilters) decisionFilters.innerHTML = '';
        if (recList) recList.innerHTML = '';

        const previousWarnings = resultsView.querySelectorAll('.alert-error');
        previousWarnings.forEach(w => w.remove());
    }

    function resetApp() {
        clearResults();
        errorView.classList.add('hidden');
        qForm.reset();

        // Go back to the welcome screen
        welcomeView.classList.remove('hidden');
        resumeIdInput.value = '';
        resumeError.classList.add('hidden');

        // Clear session ID
        currentPortfolioId = null;

        // Scroll to top
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    async function handleResume(e) {
        e.preventDefault();
        resumeError.classList.add('hidden');

        let targetId = resumeIdInput.value.trim();
        if (!targetId) {
            resumeError.textContent = "Please enter a valid Portfolio ID";
            resumeError.classList.remove('hidden');
            return;
        }

        // Clean off accidental .json extensions
        if (targetId.endsWith('.json')) {
            targetId = targetId.replace('.json', '');
        }

        // Strip out 'port_' if they provided just the raw hash by mistake, then prepend it back
        // to be extremely resillient to copy-paste errors
        if (!targetId.startsWith('port_')) {
            targetId = 'port_' + targetId;
        }

        try {
            // Lock UI while loading
            const submitBtn = resumeForm.querySelector('button[type="submit"]');
            const originalText = submitBtn.textContent;
            submitBtn.textContent = "Locating...";
            submitBtn.disabled = true;

            const response = await fetch(`/api/portfolio/${targetId}`);

            if (!response.ok) {
                if (response.status === 404) {
                    throw new Error("Portfolio ID not found. It may have expired. Start fresh or try again.");
                }
                throw new Error("Failed to load portfolio.");
            }

            const savedPortfolio = await response.json();

            // Set global tracking ID if success
            currentPortfolioId = savedPortfolio.portfolio_id;

            // Show Active Session banner
            activePortIdDisplay.textContent = currentPortfolioId;
            activeSessionBanner.classList.remove('hidden');

            showFormView(savedPortfolio.user_answers || {});

        } catch (err) {
            resumeError.textContent = err.message;
            resumeError.classList.remove('hidden');
        } finally {
            const submitBtn = resumeForm.querySelector('button[type="submit"]');
            submitBtn.textContent = "Resume Portfolio";
            submitBtn.disabled = false;
        }
    }

    function showFormView(prefillAnswers) {
        welcomeView.classList.add('hidden');
        formView.classList.remove('hidden');

        // If we are starting fresh, make sure the banner is hidden
        if (!currentPortfolioId) {
            activeSessionBanner.classList.add('hidden');
        }

        // Pre-fill fields if we have a saved payload
        if (prefillAnswers && Object.keys(prefillAnswers).length > 0) {
            Object.entries(prefillAnswers).forEach(([key, value]) => {
                // Determine what type of input this is by selecting all matching inputs
                const elements = qForm.querySelectorAll(`[name="${key}"]`);
                if (!elements || elements.length === 0) return;

                // If its a multi-select checkbox cluster
                if (elements[0].type === 'checkbox') {
                    const valueArray = Array.isArray(value) ? value : [value];
                    elements.forEach(cb => {
                        // Only check it if the saved value is one of the valid options
                        if (valueArray.includes(cb.value)) {
                            cb.checked = true;
                        }
                    });
                }
                // If its a dropdown
                else if (elements[0].tagName.toLowerCase() === 'select') {
                    const select = elements[0];
                    // Check if the saved value exists in the dropdown options
                    const optionExists = Array.from(select.options).some(opt => opt.value === value);
                    if (optionExists) {
                        select.value = value;
                    }
                }
                // General input
                else {
                    elements[0].value = value;
                }
            });
        }
    }

    // UI Helpers
    function setLoadingState(isLoading) {
        submitBtn.disabled = isLoading;
        if (isLoading) {
            btnText.textContent = 'Analyzing...';
            btnSpinner.classList.remove('hidden');
        } else {
            btnText.textContent = 'Generate Portfolio';
            btnSpinner.classList.add('hidden');
        }
    }

    function showError(msg) {
        errorMessage.textContent = msg;
        errorView.classList.remove('hidden');
    }
});
