import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function simulator() {
    const noop = () => {};
    const drawing = new Proxy({}, { get: () => noop });
    const elements = new Map();
    const element = () => ({
        value: '0', style: {}, textContent: '', addEventListener: noop,
        getContext: () => drawing, classList: { add: noop, remove: noop },
        appendChild: noop, parentElement: { clientWidth: 800, clientHeight: 600 }
    });
    const document = {
        body: element(),
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, element());
            return elements.get(id);
        }
    };
    const context = vm.createContext({
        document, window: { addEventListener: noop }, Image: class {},
        requestAnimationFrame: noop, cancelAnimationFrame: noop,
        setTimeout: noop, clearTimeout: noop, matchMedia: noop
    });
    vm.runInContext(readFileSync(new URL('../script.js', import.meta.url), 'utf8'), context);
    vm.runInContext('width = 800; height = 600', context);
    return { context, indicator: elements.get('handicapIndicator') };
}

test('manual restart clears the handicap, automatic restart preserves it', () => {
    const { context, indicator } = simulator();
    vm.runInContext('BALANCING.active = true; BALANCING.handicapType = TYPES.ROCK', context);
    indicator.style.display = 'inline';
    vm.runInContext('startSimulation(true)', context);
    assert.equal(vm.runInContext('BALANCING.active', context), false);
    assert.equal(vm.runInContext('BALANCING.handicapType', context), null);
    assert.equal(indicator.style.display, 'none');

    vm.runInContext('BALANCING.active = true; BALANCING.handicapType = TYPES.ROCK', context);
    indicator.style.display = 'inline';
    vm.runInContext('startSimulation(false)', context);
    assert.equal(vm.runInContext('BALANCING.active', context), true);
    assert.equal(vm.runInContext('BALANCING.handicapType', context), 0);
    assert.equal(indicator.style.display, 'inline');
});
