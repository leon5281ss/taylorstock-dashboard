from decimal import Decimal, ROUND_HALF_UP


def liquidation_pnl(shares, average_cost, price, *, buy_fee_rate, sell_fee_rate, sell_tax_rate, minimum_fee=0):
    values = [Decimal(str(value)) for value in (shares, average_cost, price, buy_fee_rate, sell_fee_rate, sell_tax_rate, minimum_fee)]
    if any(not value.is_finite() or value < 0 for value in values) or values[0] <= 0 or values[1] <= 0:
        raise ValueError("invalid_private_inputs")
    quantity, cost, close, buy_rate, sell_rate, tax_rate, minimum = values
    purchase, sale = quantity * cost, quantity * close
    buy_fee = max(minimum, purchase * buy_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    sell_fee = max(minimum, sale * sell_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    tax = (sale * tax_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    invested = purchase + buy_fee
    pnl = sale - sell_fee - tax - invested
    return {"pnl": float(pnl), "return_rate": float(pnl / invested), "buy_fee": float(buy_fee), "sell_fee": float(sell_fee), "sell_tax": float(tax)}

