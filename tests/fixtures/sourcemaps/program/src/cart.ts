import {divide} from './math';

type Item = {name: string; price: number};

export class Cart {
  items: Item[];
  constructor(items: Item[]) {
    this.items = items;
  }
// @@V2   describe(): string {
// @@V2     return this.items.map(item => `${item.name}: ${item.price}`).join(', ');
// @@V2   }
  total(): number {
    return this.items.reduce((acc, item) => acc + item.price, 0);
  }
  perItem(): number {
    return divide(this.total(), this.items.length);
  }
  get label(): string {
    return this.items[0].name.toUpperCase();
  }
  static fromJSON(json: string): Cart {
    const parse = (text: string) => JSON.parse(text);
    return new Cart(parse(json));
  }
}
