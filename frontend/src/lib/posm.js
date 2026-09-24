/**
 * Is this free line point-of-sale material rather than stock the shop can sell?
 *
 * A shelf strip, a danglers pack, a wobbler, a sticker. It is dispatched with the order and it
 * costs somebody money, but it is not a saleable SKU: it must never be counted into sales volume
 * or offtake, and it must never sit in the same list as a free case of soap. `FieldMate Free
 * Goods` carries an `is_posm` flag for exactly this reason.
 *
 * This lives here rather than in either screen because the scheme preview and the order review
 * both have to answer it, and they have to answer it the *same* way. They did not: one counted
 * two shelf strips as free stock and the other did not, so the same order read as "1 free unit"
 * on one screen and "3 free units" on the next. A rep who sees two different numbers for the same
 * thing stops believing both of them.
 *
 * **`catalogue.items` does not send `is_posm` per item yet**, so the flag is read first and the
 * item group is the fallback. This is the one place to change once the payload carries it.
 *
 * Deliberately no guess from the item name. A saleable SKU mislabelled as display material drops
 * straight out of the volume a rep is measured on, which is a worse failure than a POSM row
 * sitting in the wrong list, and product names are exactly where a pattern like this goes wrong.
 */
const POSM_GROUP = /posm|point[ -]of[ -]sale|display material|merchandis/i

export function isPosmItem(item) {
  if (!item) return false
  if (item.is_posm !== undefined && item.is_posm !== null) return !!item.is_posm
  return POSM_GROUP.test(item.item_group || '')
}
