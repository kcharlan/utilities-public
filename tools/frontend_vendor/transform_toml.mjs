export function transformToml(source) {
  const match = source.match(/export\s*\{([^}]+)\};?\s*(?:\/\/[#@]\s*sourceMappingURL=.*)?\s*$/);
  if (!match) throw Error('TOML export statement not found');
  const bindings = Object.fromEntries(match[1].split(',').map(part => {
    const [local, exported = local] = part.trim().split(/\s+as\s+/);
    return [exported, local];
  }));
  if (!bindings.parse || !bindings.stringify) throw Error('TOML parse/stringify exports missing');
  return `(function(){\n${source.slice(0,match.index)}\nwindow.TOML={parse:${bindings.parse},stringify:${bindings.stringify}};\n})();\n`;
}
