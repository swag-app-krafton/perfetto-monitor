// Metro config for the symbolicate test program: React Native's defaults,
// resolved against an app's node_modules (RN_NODE_MODULES), without
// InitializeCore or RN's polyfills so the bundle runs in a bare Hermes host.
const path = require('path');
const NM = process.env.RN_NODE_MODULES;
const {getDefaultConfig, mergeConfig} = require(NM + '/@react-native/metro-config/dist/index.js');
module.exports = mergeConfig(getDefaultConfig(__dirname), {
  projectRoot: __dirname,
  watchFolders: [NM],
  resolver: {nodeModulesPaths: [path.join(__dirname, 'node_modules'), NM]},
  serializer: {getModulesRunBeforeMainModule: () => [], getPolyfills: () => []},
});
