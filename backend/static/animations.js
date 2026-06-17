function initAnimations() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
                entry.target.style.opacity = '1';
                const children = entry.target.querySelectorAll('.anim-card, .anim-card-left, .anim-card-right, .anim-card-scale');
                children.forEach((el, i) => {
                    setTimeout(() => {
                        el.classList.add('visible');
                        el.style.opacity = '1';
                        el.style.transform = 'translateY(0) scale(1)';
                    }, i * 100);
                });
            }
        });
    }, { threshold: 0.1, rootMargin: '0px 0px -50px 0px' });

    document.querySelectorAll('.anim-section').forEach(section => {
        section.style.opacity = '0';
        section.style.transition = 'opacity 0.8s ease-out';
        observer.observe(section);
    });

    const heroObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) entry.target.classList.add('visible');
        });
    }, { threshold: 0.1 });
    document.querySelectorAll('.anim-hero').forEach(el => heroObserver.observe(el));

    document.querySelectorAll('.anim-stagger').forEach((el, i) => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(30px)';
        el.style.transition = `all 0.6s ease-out ${i * 0.12}s`;
    });

    const staggerObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const els = entry.target.querySelectorAll('.anim-stagger');
                els.forEach((el, i) => {
                    setTimeout(() => {
                        el.style.opacity = '1';
                        el.style.transform = 'translateY(0)';
                    }, i * 80);
                });
            }
        });
    }, { threshold: 0.1 });
    document.querySelectorAll('.anim-stagger-group').forEach(el => staggerObserver.observe(el));

    const pricingObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) entry.target.classList.add('visible');
        });
    }, { threshold: 0.15 });
    document.querySelectorAll('.anim-pricing').forEach(el => pricingObserver.observe(el));

    let statsCounted = false;
    const statsObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting && !statsCounted) {
                statsCounted = true;
                entry.target.querySelectorAll('.stat-counter').forEach(c => {
                    const target = parseFloat(c.dataset.target);
                    const prefix = c.dataset.prefix || '';
                    const suffix = c.dataset.suffix || '';
                    animateCounter(c, target, prefix, suffix);
                });
            }
        });
    }, { threshold: 0.5 });
    const statsEl = document.getElementById('hero-stats');
    if (statsEl) statsObserver.observe(statsEl);
}

function animateCounter(el, target, prefix, suffix) {
    const duration = 2000;
    const steps = 60;
    const increment = target / steps;
    let current = 0;
    let step = 0;
    const timer = setInterval(() => {
        step++;
        current += increment;
        if (step >= steps) {
            current = target;
            clearInterval(timer);
        }
        el.textContent = prefix + formatNumber(Math.floor(current)) + suffix;
    }, duration / steps);
}

function formatNumber(n) {
    if (n >= 1000000000) return (n / 1000000000).toFixed(1) + 'B';
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(0) + 'K';
    return n.toString();
}

document.addEventListener('DOMContentLoaded', () => {
    initAnimations();
});
