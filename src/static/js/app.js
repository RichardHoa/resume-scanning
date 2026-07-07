document.addEventListener('DOMContentLoaded', () => {
    // Current File State
    let selectedFile = null;
    let extractedJsonData = null;

    // DOM Elements
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file-input');
    const browseLink = document.querySelector('.browse-link');
    const filePreview = document.getElementById('file-preview');
    const previewFilename = document.getElementById('preview-filename');
    const previewFilesize = document.getElementById('preview-filesize');
    const btnRemoveFile = document.getElementById('btn-remove-file');
    const btnExtract = document.getElementById('btn-extract');
    
    const uploadSection = document.getElementById('upload-section');
    const resultsSection = document.getElementById('results-section');
    const jsonOutput = document.getElementById('json-output');
    
    const btnCopy = document.getElementById('btn-copy');
    const btnDownload = document.getElementById('btn-download');
    const btnReset = document.getElementById('btn-reset');
    
    const loaderOverlay = document.getElementById('loader-overlay');
    const loaderTitle = document.getElementById('loader-title');
    const loaderDesc = document.getElementById('loader-desc');
    const loaderProgress = document.getElementById('loader-progress');
    
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    // Load server configuration
    fetchConfig();

    // 1. Setup Server Configuration Info
    async function fetchConfig() {
        try {
            const res = await fetch('/api/config');
            const data = await res.json();
            
            // Format model name for UI
            const modelParts = data.model.split('/');
            const shortModelName = modelParts[modelParts.length - 1];
            document.getElementById('val-model').textContent = shortModelName + (data.mock ? ' (Mock)' : '');
            
            // Format mode badge
            const modeText = data.image_mode ? 'Vision (Image)' : 'Text Only';
            document.getElementById('val-mode').textContent = modeText;
        } catch (e) {
            console.error('Failed to load server configuration:', e);
            document.getElementById('val-model').textContent = 'Unknown';
            document.getElementById('val-mode').textContent = 'Unknown';
        }
    }

    // 2. Drag & Drop File Handlers
    browseLink.addEventListener('click', () => fileInput.click());
    
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });

    ['dragenter', 'dragover'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
        }, false);
    });

    dropzone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
            handleFileSelect(files[0]);
        }
    });

    function handleFileSelect(file) {
        if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
            alert('Only PDF files are supported.');
            return;
        }
        
        selectedFile = file;
        
        // Show file preview
        previewFilename.textContent = file.name;
        previewFilesize.textContent = formatBytes(file.size);
        
        dropzone.style.display = 'none';
        filePreview.style.display = 'flex';
        btnExtract.disabled = false;
    }

    btnRemoveFile.addEventListener('click', () => {
        selectedFile = null;
        fileInput.value = '';
        filePreview.style.display = 'none';
        dropzone.style.display = 'flex';
        btnExtract.disabled = true;
    });

    // 3. Extraction Action Handler
    btnExtract.addEventListener('click', async () => {
        if (!selectedFile) return;
        
        // Open Loader overlay
        showLoader();
        
        const formData = new FormData();
        formData.append('file', selectedFile);
        
        try {
            const response = await fetch('/api/extract', {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || 'Failed during document processing.');
            }
            
            const resultData = await response.json();
            const extractionTime = response.headers.get('X-Extraction-Time');
            extractedJsonData = resultData;
            
            // Success! Load data
            displayResults(resultData, extractionTime);
            
        } catch (e) {
            alert('Error processing file: ' + e.message);
        } finally {
            hideLoader();
        }
    });

    // 4. Loading Indicators and Timer text shifts
    let loaderInterval = null;
    function showLoader() {
        loaderOverlay.style.display = 'flex';
        loaderProgress.style.style = 'width: 5%';
        
        const loaderStates = [
            { title: 'Reading PDF format...', desc: 'Extracting digital text layers and compiling coordinate grids.' },
            { title: 'Analyzing Layout...', desc: 'Identifying multi-column bounding boxes, sidebars, and structural headers.' },
            { title: 'Running LLM Inference...', desc: 'Analyzing CV details using local deep learning model. This might take up to a minute.' },
            { title: 'Structuring JSON Schema...', desc: 'Mapping work history, educational degrees, and skill definitions to JSON schema.' },
            { title: 'Validating output formats...', desc: 'Applying JSON repairing routines and filling missing values.' }
        ];
        
        let stateIdx = 0;
        loaderTitle.textContent = loaderStates[0].title;
        loaderDesc.textContent = loaderStates[0].desc;
        
        loaderInterval = setInterval(() => {
            stateIdx = (stateIdx + 1) % loaderStates.length;
            loaderTitle.textContent = loaderStates[stateIdx].title;
            loaderDesc.textContent = loaderStates[stateIdx].desc;
        }, 12000);
    }

    function hideLoader() {
        clearInterval(loaderInterval);
        loaderOverlay.style.display = 'none';
    }

    // 5. Results Display Routine
    function displayResults(data, extractionTime) {
        // Show raw JSON in the code pane
        jsonOutput.textContent = JSON.stringify(data, null, 2);
        
        // Render parsed data
        renderParsedData(data);
        
        // Display extraction time if available
        const badgeTime = document.getElementById('badge-time');
        const valTime = document.getElementById('val-time');
        if (extractionTime && badgeTime && valTime) {
            valTime.textContent = parseFloat(extractionTime).toFixed(2) + 's';
            badgeTime.style.display = 'flex';
        } else if (badgeTime) {
            badgeTime.style.display = 'none';
        }
        
        // Shift views
        uploadSection.style.display = 'none';
        resultsSection.style.display = 'flex';
    }

    // 6. JSON Structure Parsing to UI Elements
    function renderParsedData(data) {
        // --- 6.1 Profile Tab ---
        const applied = data.position_applied || {};
        document.getElementById('profile-position').textContent = applied.title || 'Job Title Not Stated';
        document.getElementById('profile-level').textContent = applied.level || 'Unknown';
        
        const basic = data.basic_information || {};
        document.getElementById('profile-email').textContent = basic.email || 'N/A';
        document.getElementById('profile-phone').textContent = basic.phone || 'N/A';
        document.getElementById('profile-location').textContent = basic.location || 'N/A';
        document.getElementById('profile-links').textContent = basic.other_info || 'N/A';
        
        document.getElementById('profile-summary').textContent = data.self_evaluation || 'No self-evaluation text provided on the resume.';
        
        // --- 6.2 Work Experience Tab ---
        const expTimeline = document.getElementById('experience-timeline');
        expTimeline.innerHTML = '';
        const jobs = data.work_experience || [];
        
        if (jobs.length === 0) {
            expTimeline.innerHTML = '<p class="summary-text" style="text-align: center; padding: 2rem 0;">No work experience detected.</p>';
        } else {
            jobs.forEach(job => {
                const card = document.createElement('div');
                card.className = 'timeline-card';
                
                let respHtml = '';
                if (job.responsibilities) {
                    respHtml = `<div class="job-responsibilities">${job.responsibilities}</div>`;
                }
                
                card.innerHTML = `
                    <div class="timeline-card-header">
                        <div>
                            <div class="job-title">${job.position || 'Employee'}</div>
                            <div class="company-name">${job.company_name || 'N/A'}</div>
                        </div>
                        <span class="job-duration">${job.duration || 'N/A'}</span>
                    </div>
                    ${job.company_description ? `<div class="company-desc">${job.company_description}</div>` : ''}
                    ${respHtml}
                `;
                expTimeline.appendChild(card);
            });
        }
        
        // --- 6.3 Education & Certifications Tab ---
        // Education
        const eduList = document.getElementById('education-list');
        eduList.innerHTML = '';
        const schools = data.education_background || [];
        
        if (schools.length === 0) {
            eduList.innerHTML = '<p class="summary-text">No education history detected.</p>';
        } else {
            schools.forEach(school => {
                const item = document.createElement('div');
                item.className = 'education-item';
                
                const metaDetails = [];
                if (school.field_of_study) metaDetails.push(`Major: ${school.field_of_study}`);
                if (school.gpa) metaDetails.push(`GPA: ${school.gpa}`);
                
                item.innerHTML = `
                    <div class="edu-header">
                        <div class="univ-name">${school.university_name || 'Institution N/A'}</div>
                        <span class="edu-year">${school.graduation_year || 'N/A'}</span>
                    </div>
                    <div class="edu-degree">${school.degree || 'Degree N/A'}</div>
                    ${metaDetails.length > 0 ? `<div class="edu-meta">${metaDetails.join(' | ')}</div>` : ''}
                `;
                eduList.appendChild(item);
            });
        }
        
        // Certifications
        const certsList = document.getElementById('certifications-list');
        certsList.innerHTML = '';
        
        // Combine professional certs and language certificates if present
        let certs = data.certifications || [];
        const languages = data.languages || [];
        
        const certItems = [];
        certs.forEach(c => {
            certItems.push({
                name: c.name,
                org: c.issuing_organization,
                dur: c.duration
            });
        });
        
        languages.forEach(l => {
            if (l.certificates && l.certificates.length > 0) {
                l.certificates.forEach(lc => {
                    certItems.push({
                        name: `${l.language} Cert: ${lc.name} ${lc.score ? `(Score: ${lc.score})` : ''}`,
                        org: lc.issuing_organization || 'Language Board',
                        dur: lc.duration
                    });
                });
            } else if (l.proficiency) {
                certItems.push({
                    name: `Language Proficiency: ${l.language}`,
                    org: l.proficiency,
                    dur: ''
                });
            }
        });
        
        if (certItems.length === 0) {
            certsList.innerHTML = '<p class="summary-text">No professional certifications or languages detected.</p>';
        } else {
            certItems.forEach(cert => {
                const card = document.createElement('div');
                card.className = 'cert-card';
                card.innerHTML = `
                    <div>
                        <div class="cert-title">${cert.name || 'Certificate'}</div>
                        <div class="cert-org">${cert.org || 'N/A'}</div>
                    </div>
                    ${cert.dur ? `<span class="cert-duration">${cert.dur}</span>` : ''}
                `;
                certsList.appendChild(card);
            });
        }
        
        // --- 6.4 Projects & Skills Tab ---
        // Skills
        const skillsList = document.getElementById('skills-list');
        skillsList.innerHTML = '';
        const skills = data.skills_and_specialties || [];
        
        if (skills.length === 0) {
            skillsList.innerHTML = '<p class="summary-text">No skills listed.</p>';
        } else {
            skills.forEach(skill => {
                const pill = document.createElement('span');
                pill.className = 'skill-pill';
                pill.textContent = skill;
                skillsList.appendChild(pill);
            });
        }
        
        // Projects
        const projectsList = document.getElementById('projects-list');
        projectsList.innerHTML = '';
        const projects = data.projects || [];
        
        if (projects.length === 0) {
            projectsList.innerHTML = '<p class="summary-text">No project work detected.</p>';
        } else {
            projects.forEach(project => {
                const card = document.createElement('div');
                card.className = 'project-card';
                card.innerHTML = `
                    <div class="project-card-header">
                        <div class="proj-name">${project.project_name || 'Unnamed Project'}</div>
                        <span class="proj-duration">${project.duration || 'N/A'}</span>
                    </div>
                    <div class="proj-desc">${project.description || 'N/A'}</div>
                `;
                projectsList.appendChild(card);
            });
        }
    }

    // 7. Tabs Controller
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.getAttribute('data-tab');
            
            // Remove active classes
            tabButtons.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            // Set active class
            btn.classList.add('active');
            document.getElementById(tabId).classList.add('active');
        });
    });

    // 8. Actions Event Handlers (Copy, Download, Reset)
    btnCopy.addEventListener('click', () => {
        if (!extractedJsonData) return;
        
        navigator.clipboard.writeText(JSON.stringify(extractedJsonData, null, 2))
            .then(() => {
                const originalText = btnCopy.innerHTML;
                btnCopy.innerHTML = '<span class="btn-icon icon-copy"></span> Copied!';
                btnCopy.style.borderColor = 'var(--success)';
                btnCopy.style.color = 'var(--success)';
                
                setTimeout(() => {
                    btnCopy.innerHTML = originalText;
                    btnCopy.style.borderColor = 'rgba(99, 102, 241, 0.2)';
                    btnCopy.style.color = '#a5b4fc';
                }, 2000);
            })
            .catch(err => {
                console.error('Failed to copy text: ', err);
            });
    });

    btnDownload.addEventListener('click', () => {
        if (!extractedJsonData) return;
        
        const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(extractedJsonData, null, 2));
        const downloadAnchor = document.createElement('a');
        
        // Use sanitized candidate name if available
        let filename = 'resume_extracted.json';
        if (selectedFile) {
            const baseName = selectedFile.name.replace(/\.[^/.]+$/, "");
            filename = `${baseName}_extracted.json`;
        }
        
        downloadAnchor.setAttribute("href", dataStr);
        downloadAnchor.setAttribute("download", filename);
        document.body.appendChild(downloadAnchor);
        downloadAnchor.click();
        downloadAnchor.remove();
    });

    btnReset.addEventListener('click', () => {
        extractedJsonData = null;
        selectedFile = null;
        fileInput.value = '';
        filePreview.style.display = 'none';
        dropzone.style.display = 'flex';
        btnExtract.disabled = true;
        
        // Hide extraction time badge
        const badgeTime = document.getElementById('badge-time');
        if (badgeTime) {
            badgeTime.style.display = 'none';
        }
        
        // Swap screens
        resultsSection.style.display = 'none';
        uploadSection.style.display = 'flex';
        
        // Reset tabs to default (first profile tab)
        tabButtons.forEach(b => b.classList.remove('active'));
        tabContents.forEach(c => c.classList.remove('active'));
        tabButtons[0].classList.add('active');
        tabContents[0].classList.add('active');
    });

    // Helper functions
    function formatBytes(bytes, decimals = 2) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }
});
