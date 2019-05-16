typedef unsigned long long size_t;
typedef signed long long ptrdiff_t;
size_t syscall(size_t sys_n, size_t arg0, size_t arg1, size_t arg2, size_t arg3);
int print(const char *str);
ptrdiff_t pyg_id = -1;
ptrdiff_t pygame_init() {
    if (pyg_id == -1) {
        pyg_id = (ptrdiff_t)syscall(0x02, 0, 0, 0, 0);
    }
    // return pyg_id;
} // print("\n".join(["%02u: %s" % (c, x.str) for c, x in enumerate(tokens[27:47
ptrdiff_t disp_id = -1;

void display_init() {
    if (pyg_id != -1) {
        syscall(0x03, (size_t)pyg_id, 0, 0, 0);
    }
}

ptrdiff_t display_set_mode(unsigned int w, unsigned int h) {
    if ((disp_id == -1) & (pyg_id != -1)) {
        size_t b = h;
        b <<= 32;
        b |= w;
        disp_id = (ptrdiff_t)syscall(0x05, (size_t)pyg_id, b, 0, 0);
    }
    return disp_id;
}

ptrdiff_t wait_event() {
    if (pyg_id == -1) return -1;
    return syscall(0x09, (size_t)pyg_id, 0, 0, 0);
}

void delete_object(ptrdiff_t obj_id) {
    syscall(0x0A, (size_t)obj_id, 0, 0, 0);
}

void display_update() {
    if (pyg_id != -1) {
        syscall(0x07, (size_t)pyg_id, 0, 0, 0);
    }
}

void pygame_quit() {
    if (pyg_id != -1) {
        syscall(0x08, (size_t)pyg_id, 0, 0, 0);
    }
}

bool running = 1;
// reverses a string 'str' of length 'len'
void reverse(char *str, int len)
{
    int i=0, j=len-1, temp;
    while (i<j)
    {
        temp = str[i];
        str[i] = str[j];
        str[j] = temp;
        i++; j--;
    }
}

 // Converts a given integer x to string str[].  d is the number
 // of digits required in output. If d is more than the number
 // of digits in x, then 0s are added at the beginning.
int intToStr(int x, char *str, int d, int radix)
{
    int i = 0;
    while (x)
    {
        char ch = (x % radix);
        if (ch >= 10) {
            ch += 'A' - 10;
        } else {
            ch += '0';
        }
        str[i++] = ch;
        x = x / radix;
    }

    // If number of digits required is more, then
    // add 0s at the beginning
    while (i < d)
        str[i++] = '0';

    reverse(str, i);
    str[i] = '\0';
    return i;
}
int intToStr(int x, char *str, int d) {
    return intToStr(x, str, d, 10);
}

char buf1[9];

void surf_fill(ptrdiff_t surf, unsigned char r, unsigned char g, unsigned char b, unsigned int flags, unsigned int x, unsigned int y, unsigned int w, unsigned int h) {
    if (surf != -1) {
        size_t b_arg = flags;
        b_arg <<= 32;
        b_arg |= ((int)r << 16) | ((int)g << 8) | b;
        intToStr((int)b_arg, (char *)buf1, 8, 16);
        // print("0x");
        // print(buf1);
        // print("\n");
        size_t c = y;
        c <<= 32;
        c |= x;
        size_t d = h;
        d <<= 32;
        d |= w;
        syscall(0x06, (size_t)surf, b_arg, c, d);
    }
}

void load_event(ptrdiff_t evt_id, char *buf) {
    if (pyg_id != -1) {
        syscall(0x0B, (size_t)pyg_id, (size_t)evt_id, (size_t)buf, 0);
    }
}

struct QuitEvent {
    unsigned int type;
};

struct KeydownEvent {
    unsigned int type;
    unsigned int key;
    unsigned int mod;
    unsigned int unicode;
};

struct KeyupEvent {
    unsigned int type;
    unsigned int key;
    unsigned int mod;
};

struct MouseMotionEvent {
    unsigned int type;
    unsigned int buttons;
    signed int x, y;
    signed int rel_x, rel_y;
};

struct MouseButtonUpEvent {
    unsigned int type;
    unsigned int button;
    signed int x, y;
};

struct MouseButtonDownEvent {
    unsigned int type;
    unsigned int button;
    signed int x, y;
};

/* struct JoyAxisMotionEvent {
    unsigned int type;
};

struct JoyBallMotionEvent {
    unsigned int type;
};

struct JoyHATMotionEvent {
    unsigned int type;
};

struct JoyButtonUpEvent {
    unsigned int type;
};

struct JoyButtonDownEvent {
    unsigned int type;
};*/

struct VideoResizeEventEvent {
    unsigned int type;
};

struct ActiveEvent {
    unsigned int type;
};

struct VideoExposeEvent {
    unsigned int type;
};


int main(int argc, char **argv) {
    pyg_id = -1;
    disp_id = -1;
    pygame_init();
    running = 1;
    display_init();
    display_set_mode((unsigned int)640, (unsigned int)480);
    int rgb_hues[10];
    rgb_hues[0] = 0x00FF0000;
    rgb_hues[1] = 0x00CC3300;
    rgb_hues[2] = 0x00887700;
    rgb_hues[3] = 0x0033BB00;
    rgb_hues[4] = 0x0000FF00;
    rgb_hues[5] = 0x0000FF00;
    rgb_hues[6] = 0x0000CC33;
    rgb_hues[7] = 0x00008877;
    rgb_hues[8] = 0x000033BB;
    rgb_hues[9] = 0x000000FF;
    size_t i = 0;
    char buf[5];
    char evt_buf[24];
    char *evt_buf_ptr = evt_buf;
    buf[4] = '\0';
    while (running) {
        unsigned char r = rgb_hues[i] >> 16;
        unsigned char g = rgb_hues[i] >> 8;
        unsigned char b = rgb_hues[i];
        // print("r: ");
        // intToStr(r, buf, 4);
        // print(buf);
        // print("\n");
        // print("g: ");
        // intToStr(g, buf, 4);
        // print(buf);
        // print("\n");
        // print("b: ");
        // intToStr(b, buf, 4);
        // print(buf);
        // print("\n");
        surf_fill(disp_id, r, g, b, (unsigned int)0, (unsigned int)0, (unsigned int)0, (unsigned int)640, (unsigned int)480);
        display_update();
        ptrdiff_t evt = wait_event();
        load_event(evt, evt_buf_ptr);
        int evt_type;
        int *tmp = (int *)evt_buf_ptr;
        evt_type = *tmp;
        if (evt_type == 12) {
            running = 0;
        }
        delete_object(evt);
        i = (i + 1) % 10;
    }
    pygame_quit();
    delete_object(disp_id);
    disp_id = -1;
    delete_object(pyg_id);
    pyg_id = -1;
    return 0;
}