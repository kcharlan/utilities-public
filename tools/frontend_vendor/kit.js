(function () {
  const { h, render, Component } = window.preact;
  const { useMemo, useLayoutEffect } = window.preactHooks;
  function Icon({ name, size = 16, strokeWidth = 2, ...rest }) {
    const nodes = Object.hasOwn(window.lucideIcons || {}, name) ? window.lucideIcons[name] : null;
    if (!nodes) { console.error(`Unknown Lucide icon: ${name}`); return null; }
    return h('svg', { xmlns: 'http://www.w3.org/2000/svg', width: size, height: size,
      viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
      'stroke-width': strokeWidth, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', ...rest },
      nodes.map(([tag, attrs]) => h(tag, attrs)));
  }
  function Portal({ children }) {
    const host = useMemo(() => document.createElement('div'), []);
    useLayoutEffect(() => {
      document.body.appendChild(host);
      return () => { render(null, host); host.remove(); };
    }, [host]);
    useLayoutEffect(() => { render(children, host); }, [children, host]);
    return null;
  }
  function shallowEqual(a, b) {
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every(key => Object.is(a[key], b[key]));
  }
  function memo(Inner, areEqual = shallowEqual) {
    return class extends Component {
      shouldComponentUpdate(next) { return !areEqual(this.props, next); }
      render(props) { return h(Inner, props); }
    };
  }
  function focusOnMount(element) { if (element) element.focus(); }
  window.frontendKit = { Icon, Portal, memo, focusOnMount };
})();
