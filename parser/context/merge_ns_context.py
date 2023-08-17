


def merge_ns_context(ns, context):
    other = context.NS_Strict(ns.name)
    # TODO: account for other = typedef
    if other is None:
        other = context.new_ns(ns.name, ns)
    elif ns.defined and other.defined:
        raise NameError("Redefinition of Namespace '%s' not allowed (yet)" % ns.name)
    elif ns.defined:
        ns.merge_to(other)
    return other
