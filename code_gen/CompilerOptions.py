from .LinkerOptions import LinkerOptions


class CompilerOptions(object):
    __slots__ = ["link_opts", "merge_and_link", "keep_local_syms"]

    def __init__(self, link_opts: LinkerOptions, merge_and_link: bool = True, keep_local_syms: bool = False):
        self.link_opts = link_opts
        self.merge_and_link = merge_and_link
        self.keep_local_syms = keep_local_syms