

export const DOMSafeUtils = {

    clearElement(element) {
        if (!element) return;
        while (element.firstChild) {
            element.removeChild(element.firstChild);
        }
    },


    setText(element, text) {
        if (!element) return;
        this.clearElement(element);
        if (text) {
            element.appendChild(document.createTextNode(text));
        }
    },


    setTextWithLineBreaks(element, text) {
        if (!element) return;
        this.clearElement(element);
        if (text) {
            const lines = text.split('\n');
            lines.forEach((line, index) => {
                if (index > 0) {
                    element.appendChild(document.createElement('br'));
                }
                element.appendChild(document.createTextNode(line));
            });
        }
    },


    setHTML(container, htmlString) {
        if (!container) return;
        this.clearElement(container);
        const parser = new DOMParser();
        try {
            const doc = parser.parseFromString(htmlString, 'text/html');
            while (doc.body.firstChild) {
                container.appendChild(doc.body.firstChild);
            }
        } catch (e) {
            console.error('Error appending HTML:', e);
        }
    },


    appendHTML(container, htmlString) {
        if (!container) return;
        const parser = new DOMParser();
        try {
            const doc = parser.parseFromString(htmlString, 'text/html');
            while (doc.body.firstChild) {
                container.appendChild(doc.body.firstChild);
            }
        } catch (e) {
            console.error('Error appending HTML:', e);
        }
    },


    createElementFromHTML(htmlString) {
        const parser = new DOMParser();
        try {
            const doc = parser.parseFromString(htmlString, 'text/html');
            if (doc.body.firstChild && doc.body.firstChild.tagName !== 'PARSERERROR') {
                return doc.body.firstChild;
            }
            return null;
        } catch (e) {
            console.error('Error parsing HTML:', e);
            return null;
        }
    },


    createSVGFromString(svgString) {
        try {
            const parser = new DOMParser();
            const doc = parser.parseFromString(svgString, 'image/svg+xml');
            if (doc.documentElement && doc.documentElement.tagName !== 'parsererror') {
                return doc.documentElement;
            }
            return null;
        } catch (e) {
            console.error('Error parsing SVG:', e);
            return null;
        }
    },


    createButton(options = {}) {
        const button = document.createElement('button');
        if (options.text) button.textContent = options.text;
        if (options.className) button.className = options.className;
        if (options.title) button.title = options.title;
        if (options.onClick) button.addEventListener('click', options.onClick);
        return button;
    },


    createElement(tagName, text = '', className = '') {
        const element = document.createElement(tagName);
        if (text) element.textContent = text;
        if (className) element.className = className;
        return element;
    },


    insertBefore(target, elements) {
        if (!target || !target.parentNode) return;
        const nodeList = Array.isArray(elements) ? elements : [elements];
        nodeList.forEach(el => {
            if (el && el.parentNode) {
                target.parentNode.insertBefore(el, target);
            }
        });
    },


    insertAfter(target, elements) {
        if (!target || !target.parentNode) return;
        const nodeList = Array.isArray(elements) ? elements : [elements];
        nodeList.reverse().forEach(el => {
            if (el && el.parentNode) {
                target.parentNode.insertBefore(el, target.nextSibling);
            }
        });
    },


    replaceElement(target, replacement) {
        if (!target || !target.parentNode) return;
        const nodeList = Array.isArray(replacement) ? replacement : [replacement];
        if (nodeList.length === 0) {
            target.remove();
            return;
        }
        nodeList.forEach((el, index) => {
            if (index === 0) {
                target.parentNode.replaceChild(el, target);
            } else {
                target.parentNode.insertBefore(el, target.nextSibling);
            }
        });
    },


    setAttributes(element, attributes = {}) {
        if (!element) return;
        Object.entries(attributes).forEach(([key, value]) => {
            if (value === null || value === undefined) {
                element.removeAttribute(key);
            } else {
                element.setAttribute(key, value);
            }
        });
    },


    addClass(element, ...classNames) {
        if (!element) return;
        element.classList.add(...classNames);
    },


    removeClass(element, ...classNames) {
        if (!element) return;
        element.classList.remove(...classNames);
    },


    toggleClass(element, className, force) {
        if (!element) return;
        element.classList.toggle(className, force);
    }
};
