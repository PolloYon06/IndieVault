(function () {
    const specsElement = document.getElementById('chart-specs');
    if (!specsElement || typeof Chart === 'undefined') return;

    const specs = JSON.parse(specsElement.textContent);
    let instances = [];

    function readPalette() {
        const css = getComputedStyle(document.documentElement);
        return {
            lime: css.getPropertyValue('--lime').trim() || '#d6f36a',
            lilac: css.getPropertyValue('--lilac').trim() || '#c2a8ff',
            muted: css.getPropertyValue('--muted').trim() || '#9aa0b4',
            line: css.getPropertyValue('--line').trim() || 'rgba(205, 215, 245, 0.14)',
        };
    }

    function renderCharts() {
        instances.forEach((chart) => chart.destroy());
        instances = [];

        const palette = readPalette();
        const resolveColor = (color) => palette[color] || color;
        const resolveColors = (colors) => (
            Array.isArray(colors) ? colors.map(resolveColor) : resolveColor(colors)
        );

        Chart.defaults.color = palette.muted;
        Chart.defaults.borderColor = palette.line;
        Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;

        specs.forEach((spec) => {
            const canvas = document.getElementById(spec.id);
            if (!canvas) return;

            const isBar = spec.type === 'bar';
            const isLine = spec.type === 'line';
            const isDoughnut = spec.type === 'doughnut';
            const valueAxis = {
                beginAtZero: true,
                grid: { color: palette.line },
                ticks: { precision: 0 },
            };
            const categoryAxis = {
                grid: { display: false },
                ticks: { autoSkip: true, maxRotation: 0 },
            };

            instances.push(new Chart(canvas, {
                type: spec.type,
                data: {
                    labels: spec.labels,
                    datasets: [{
                        data: spec.values,
                        backgroundColor: isLine ? 'transparent' : resolveColors(spec.colors),
                        borderColor: isLine ? resolveColor(spec.colors) : resolveColors(spec.colors),
                        borderWidth: isLine ? 2 : 0,
                        pointBackgroundColor: isLine ? resolveColor(spec.colors) : undefined,
                        pointRadius: isLine ? 3 : undefined,
                        tension: 0.35,
                        fill: false,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    indexAxis: spec.horizontal ? 'y' : 'x',
                    cutout: isDoughnut ? (spec.gauge ? '72%' : '58%') : undefined,
                    plugins: {
                        legend: {
                            display: isDoughnut && !spec.gauge,
                            position: 'bottom',
                            labels: { boxWidth: 12, boxHeight: 12, usePointStyle: true },
                        },
                    },
                    scales: isBar
                        ? (spec.horizontal
                            ? { x: valueAxis, y: categoryAxis }
                            : { x: categoryAxis, y: valueAxis })
                        : isLine
                            ? { x: categoryAxis, y: valueAxis }
                            : {},
                },
            }));
        });
    }

    renderCharts();
    new MutationObserver(renderCharts).observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme'],
    });
})();
