class ParsingError(Exception):
    TOKEN_LOOK_OFFSET = 5

    def __init__(self, tokens, token_index, msg):
        super(ParsingError, self).__init__(tokens, token_index, msg)
        a = max(0, token_index - self.TOKEN_LOOK_OFFSET)
        b = min(len(tokens), token_index + self.TOKEN_LOOK_OFFSET)
        self.tokens = tokens[a:b]
        self.a = a
        self.token_index = token_index
        self.msg = msg

    def __str__(self):
        return "tokens around c = %u, {%s}\n  MESSAGE: %s" % (
            self.token_index,
            ", ".join([
                "%u: %r" % (self.a + x, self.tokens[x])
                for x in range(len(self.tokens))
            ]),
            self.msg
        )
