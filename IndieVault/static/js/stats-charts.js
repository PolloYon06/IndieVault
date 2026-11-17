(function () {
    const specsElement = document.getElementById('chart-specs');
    if (!specsElement || typeof Chart === 'undefined') return;

    const specs = JSON.parse(specsElement.textContent);
    let instances = [];

    function readPalette() {
        // El body lleva la clase de la sección, que redefine --lime.
        const css = getComputedStyle(document.body);
        return {
            lime: css.getPropertyValue('--lime').trim() || '#d6f36a',
            lilac: css.getPropertyValue('--lilac').trim() || '#c2a8ff',
            muted: css.getPropertyValue('--muted').trim() || '#9aa0b4',
            line: css.getPropertyValue('--line').trim() || 'rgba(205, 215, 245, 0.14)',
        };
    }

    function withAlpha(color, alpha) {
        if (!color) return color;

        if (color.startsWith('#')) {
            const hex = color.slice(1);
            const expanded = hex.length === 3
                ? hex.split('').map((value) => value + value).join('')
                : hex;
            const number = parseInt(expanded, 16);
            const r = (number >> 16) & 255;
            const g = (number >> 8) & 255;
            const b = number & 255;
            return `rgba(${r}, ${g}, ${b}, ${alpha})`;
        }

        if (color.startsWith('rgb(')) {
            return color.replace('rgb(', 'rgba(').replace(')', `, ${alpha})`);
        }

        return color;
    }

    function cycleColors(colors, length) {
        if (!Array.isArray(colors)) {
            return Array.from({ length }, () => colors);
        }
        if (!colors.length) return colors;
        return Array.from({ length }, (_, index) => colors[index % colors.length]);
    }

    function createChart(canvas, spec, palette) {
        const resolveColor = (color) => palette[color] || color;
        const resolveColors = (colors) => (
            Array.isArray(colors) ? colors.map(resolveColor) : resolveColor(colors)
        );

        const isBar = spec.type === 'bar';
        const isLine = spec.type === 'line';
        const isDoughnut = spec.type === 'doughnut';
        const isRadar = spec.type === 'radar';
        const isPolar = spec.type === 'polarArea';
        const isBubble = spec.type === 'bubble';

        const baseColor = resolveColor(spec.colors);
        const paletteColors = cycleColors(
            resolveColors(spec.colors),
            spec.values ? spec.values.length : 0
        );

        const valueAxis = {
            beginAtZero: true,
            grid: { color: palette.line },
            ticks: { precision: 0 },
        };
        const categoryAxis = {
            grid: { display: false },
            ticks: { autoSkip: true, maxRotation: 0 },
        };
        const radialAxis = {
            beginAtZero: true,
            grid: { color: palette.line },
            angleLines: { color: palette.line },
            ticks: { display: false, precision: 0 },
        };

        let data;
        let options = {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 550 },
            plugins: {
                legend: {
                    display: isDoughnut || isPolar || isRadar,
                    position: 'bottom',
                    labels: {
                        boxWidth: 12,
                        boxHeight: 12,
                        usePointStyle: true,
                        padding: 14,
                    },
                },
            },
        };

        if (isBubble) {
            data = {
                datasets: [{
                    label: spec.title,
                    data: spec.points,
                    backgroundColor: withAlpha(baseColor, 0.5),
                    borderColor: baseColor,
                    borderWidth: 1,
                    hoverBackgroundColor: withAlpha(baseColor, 0.8),
                }],
            };
            options.plugins.legend.display = false;
            options.plugins.tooltip = {
                callbacks: {
                    label(context) {
                        return context.raw.label || `${context.raw.x}: ${context.raw.y}`;
                    },
                },
            };
            options.scales = {
                x: {
                    grid: { color: palette.line },
                    ticks: { precision: 0, maxRotation: 0 },
                    title: { display: true, text: 'Año' },
                },
                y: {
                    beginAtZero: true,
                    grid: { color: palette.line },
                    title: { display: true, text: 'Precio medio ($)' },
                },
            };
        } else if (isRadar) {
            data = {
                labels: spec.labels,
                datasets: [{
                    label: spec.title,
                    data: spec.values,
                    backgroundColor: withAlpha(baseColor, 0.18),
                    borderColor: baseColor,
                    borderWidth: 2,
                    pointBackgroundColor: baseColor,
                    pointBorderColor: baseColor,
                    pointRadius: 3,
                }],
            };
            options.plugins.legend.display = false;
            options.scales = {
                r: {
                    ...radialAxis,
                    pointLabels: {
                        color: palette.muted,
                        font: { size: 10, weight: '600' },
                    },
                },
            };
        } else if (isPolar) {
            data = {
                labels: spec.labels,
                datasets: [{
                    data: spec.values,
                    backgroundColor: paletteColors.map((color) => withAlpha(color, 0.55)),
                    borderColor: paletteColors,
                    borderWidth: 1,
                }],
            };
            options.scales = { r: radialAxis };
        } else {
            data = {
                labels: spec.labels,
                datasets: [{
                    data: spec.values,
                    backgroundColor: isLine ? 'transparent' : paletteColors,
                    borderColor: isLine ? baseColor : paletteColors,
                    borderWidth: isLine ? 2 : (isBar ? 0 : 1),
                    pointBackgroundColor: isLine ? baseColor : undefined,
                    pointBorderColor: isLine ? baseColor : undefined,
                    pointRadius: isLine ? 3 : undefined,
                    pointHitRadius: isLine ? 12 : undefined,
                    tension: 0.35,
                    fill: false,
                }],
            };
            options.indexAxis = spec.horizontal ? 'y' : 'x';
            options.cutout = isDoughnut ? (spec.gauge ? '72%' : '58%') : undefined;
            options.plugins.legend.display = isDoughnut && !spec.gauge;
            options.scales = isBar
                ? (spec.horizontal
                    ? { x: valueAxis, y: categoryAxis }
                    : { x: categoryAxis, y: valueAxis })
                : isLine
                    ? { x: categoryAxis, y: valueAxis }
                    : {};
        }

        if (spec.levels && Object.keys(spec.levels).length && spec.labels) {
            options.onHover = (event, elements) => {
                if (event.native) {
                    event.native.target.style.cursor = elements.length
                        ? 'pointer'
                        : 'default';
                }
            };
            options.onClick = (event, elements) => {
                if (!elements.length) return;
                const label = spec.labels[elements[0].index];
                const level = spec.levels[label];
                if (!level) return;

                const card = canvas.closest('.stat-card');
                if (card) openLevel(card, level, palette);
            };
        }

        return new Chart(canvas, {
            type: spec.type,
            data,
            options,
        });
    }

    function closeLevel(host) {
        if (host._ivChart) {
            const index = instances.indexOf(host._ivChart);
            if (index !== -1) instances.splice(index, 1);
            host._ivChart.destroy();
            host._ivChart = null;
        }
        host.innerHTML = '';
        host.hidden = true;
    }

    function openLevel(card, level, palette) {
        const host = card.querySelector('.chart-level');
        if (!host) return;

        closeLevel(host);
        host.hidden = false;

        const head = document.createElement('div');
        head.className = 'chart-level-head';

        const title = document.createElement('p');
        title.className = 'chart-level-title';
        title.textContent = level.title || 'Desglose';

        const back = document.createElement('button');
        back.type = 'button';
        back.className = 'chart-back';
        back.textContent = '← Volver';
        back.addEventListener('click', () => closeLevel(host));

        head.append(title, back);
        host.append(head);

        if (level.empty) {
            const empty = document.createElement('p');
            empty.className = 'chart-empty';
            empty.textContent = level.empty_text || 'Sin datos para este desglose.';
            host.append(empty);
            return;
        }

        const box = document.createElement('div');
        box.className = 'chart-box chart-level-box';

        const canvas = document.createElement('canvas');
        canvas.setAttribute('role', 'img');
        canvas.setAttribute('aria-label', level.title || 'Desglose');
        box.append(canvas);
        host.append(box);

        const chart = createChart(canvas, level, palette);
        host._ivChart = chart;
        instances.push(chart);
    }

    function renderCharts() {
        instances.forEach((chart) => chart.destroy());
        instances = [];

        // Al cambiar de tema se reconstruyen los gráficos y se cierran los
        // desgloses abiertos para no dejar canvas huérfanos.
        document.querySelectorAll('.chart-level').forEach((host) => {
            host._ivChart = null;
            host.innerHTML = '';
            host.hidden = true;
        });

        const palette = readPalette();

        Chart.defaults.color = palette.muted;
        Chart.defaults.borderColor = palette.line;
        Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;

        specs.forEach((spec) => {
            const canvas = document.getElementById(spec.id);
            if (!canvas) return;
            instances.push(createChart(canvas, spec, palette));
        });
    }

    renderCharts();
    new MutationObserver(renderCharts).observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme'],
    });
})();
