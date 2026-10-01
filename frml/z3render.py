"""Rendering of Z3 model values into compact, Frml-friendly form."""

import z3


def render_model(model):
    """Turn a Z3 model into a list of readable `name = value` entries."""
    entries = []
    for decl in model.decls():
        name = decl.name()
        if "!" not in name:
            # Skip Z3-internal constants (e.g. div0/mod0) and other
            # declarations that do not correspond to a Frml source symbol.
            continue
        base = name.rsplit("!", 1)[0]
        value = model[decl]
        if base.endswith("_len"):
            label = f"length({base[:-4]})"
        else:
            label = base
        entries.append(f"{label} = {render_model_value(value)}")
    return sorted(entries)


def render_model_value(value):
    """Render one Z3 model value in a compact, Frml-friendly form."""
    if z3.is_quantifier(value) and value.is_lambda():
        return _render_lambda(value)
    if not z3.is_app(value):
        return value.sexpr()
    head = value.decl().name()
    match head:
        case "const":
            return f"all -> {render_model_value(value.arg(0))}"
        case "store":
            entries = []
            cur = value
            while cur.decl().name() == "store":
                index = render_model_value(cur.arg(1))
                item = render_model_value(cur.arg(2))
                entries.append(f"{index}: {item}")
                cur = cur.arg(0)
            if cur.decl().name() == "const":
                entries.append(f"else: {render_model_value(cur.arg(0))}")
            return "{" + ", ".join(entries) + "}"
        case "if":
            cond = value.arg(0).sexpr()
            then = render_model_value(value.arg(1))
            else_ = render_model_value(value.arg(2))
            return f"({cond} ? {then} : {else_})"
    if z3.is_int_value(value):
        return str(value.as_long())
    if z3.is_bool(value):
        return "true" if z3.is_true(value) else "false"
    if z3.is_string_value(value):
        return f'"{value.as_string()}"'
    return value.sexpr()


def _render_lambda(value):
    """Render an SMT `lambda` array value as a readable piecewise term.

    Z3 models a piecewise array as a `Lambda(index, ite(...))` expression.
    We substitute a readable index name for the de Bruijn bound variable and
    let `render_model_value` walk the `ite` tree.
    """
    if value.num_vars() != 1:
        return value.sexpr()
    index = z3.Int("i")
    body = z3.substitute(value.body(), (z3.Var(0, value.var_sort(0)), index))
    return render_model_value(body)
