import {average} from './src/math';
import {Cart} from './src/cart';
import {loadProfile, handlers} from './src/api';
import {fireSettingsChanged} from './src/events';
import {checkPayee, scanAmounts} from './src/lib';
import {makeCounter} from './src/nested';

function report(label, error) {
  global.print('@@STACK ' + label + '\n' + error.stack + '\n@@END');
}

const scenarios = {
  nested_function: () => average([]),
  class_method: () => new Cart([]).perItem(),
  getter: () => new Cart([]).label,
  arrow_native: () => Cart.fromJSON('{not json'),
  object_method: () => handlers.onPress({}),
  rn_internal: () => fireSettingsChanged(),
  third_party: () => checkPayee(null),
  third_party_callback: () => scanAmounts([5, -1]),
  closure: () => {
    const next = makeCounter(1);
    next();
    next();
  },
};

for (const label of Object.keys(scenarios)) {
  try {
    scenarios[label]();
  } catch (error) {
    report(label, error);
  }
}

loadProfile(null).catch(error => report('async_function', error));

function boot() {
  throw new Error('fatal during boot');
}
boot();
