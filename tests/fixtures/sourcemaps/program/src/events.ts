import EventEmitter from 'react-native/Libraries/vendor/emitter/EventEmitter';

export function fireSettingsChanged(): void {
  const emitter = new EventEmitter();
  emitter.addListener('settings', () => {
    throw new Error('listener failed');
  });
  emitter.emit('settings');
}
