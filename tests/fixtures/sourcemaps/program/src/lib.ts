import {validate, eachItem} from 'fake-lib';

export function checkPayee(payee: string | null): string {
  return validate(payee);
}

export function scanAmounts(amounts: number[]): void {
  eachItem(amounts, (amount: number) => {
    if (amount < 0) {
      throw new Error('negative amount');
    }
  });
}
