"""
Implement the cmath module functions.
"""

from __future__ import print_function, absolute_import, division

import cmath
import math

import llvm.core as lc
from llvm.core import Type

from numba.targets.imputils import implement, Registry
from numba import types, cgutils, utils
from numba.typing import signature
from . import builtins, mathimpl


registry = Registry()
register = registry.register


def is_nan(builder, z):
    return builder.or_(mathimpl.is_nan(builder, z.real),
                       mathimpl.is_nan(builder, z.imag))

def is_inf(builder, z):
    return builder.or_(mathimpl.is_inf(builder, z.real),
                       mathimpl.is_inf(builder, z.imag))

def is_finite(builder, z):
    return builder.and_(mathimpl.is_finite(builder, z.real),
                        mathimpl.is_finite(builder, z.imag))


@register
@implement(cmath.isnan, types.Kind(types.Complex))
def isnan_float_impl(context, builder, sig, args):
    [typ] = sig.args
    [value] = args
    cplx_cls = context.make_complex(typ)
    z = cplx_cls(context, builder, value=value)
    return is_nan(builder, z)

@register
@implement(cmath.isinf, types.Kind(types.Complex))
def isinf_float_impl(context, builder, sig, args):
    [typ] = sig.args
    [value] = args
    cplx_cls = context.make_complex(typ)
    z = cplx_cls(context, builder, value=value)
    return is_inf(builder, z)


if utils.PYVERSION >= (3, 2):
    @register
    @implement(cmath.isfinite, types.Kind(types.Complex))
    def isfinite_float_impl(context, builder, sig, args):
        [typ] = sig.args
        [value] = args
        cplx_cls = context.make_complex(typ)
        z = cplx_cls(context, builder, value=value)
        return is_finite(builder, z)


@register
@implement(cmath.rect, types.Kind(types.Float), types.Kind(types.Float))
def rect_impl(context, builder, sig, args):
    [r, phi] = args
    # We can't call math.isfinite() inside rect() below because it
    # only exists on 3.2+.
    phi_is_finite = mathimpl.is_finite(builder, phi)

    def rect(r, phi, phi_is_finite):
        if not phi_is_finite:
            if not r:
                # cmath.rect(0, phi={inf, nan}) = 0
                return complex(r, r)
            if math.isinf(r):
                # cmath.rect(inf, phi={inf, nan}) = inf + j phi
                return complex(r, phi)
        if not phi:
            # cmath.rect(r, 0) = r
            return complex(r, phi)
        return r * complex(math.cos(phi), math.sin(phi))

    inner_sig = signature(sig.return_type, *sig.args + (types.boolean,))
    return context.compile_internal(builder, rect, inner_sig,
                                    args + [phi_is_finite])


def intrinsic_complex_unary(inner_func):
    def wrapper(context, builder, sig, args):
        [typ] = sig.args
        [value] = args
        cplx_cls = context.make_complex(typ)
        z = cplx_cls(context, builder, value=value)
        x = z.real
        y = z.imag
        # Same as above: math.isfinite() is unavailable on 2.x so we precompute
        # its value and pass it to the pure Python implementation.
        x_is_finite = mathimpl.is_finite(builder, x)
        y_is_finite = mathimpl.is_finite(builder, y)
        inner_sig = signature(sig.return_type,
                              *(typ.underlying_float,) * 2 + (types.boolean,) * 2)
        return context.compile_internal(builder, inner_func, inner_sig,
                                        (x, y, x_is_finite, y_is_finite))
    return wrapper


NAN = float('nan')
INF = float('inf')

@register
@implement(cmath.exp, types.Kind(types.Complex))
@intrinsic_complex_unary
def exp_impl(x, y, x_is_finite, y_is_finite):
    """cmath.exp(x + y j)"""
    if x_is_finite:
        if y_is_finite:
            c = math.cos(y)
            s = math.sin(y)
            r = math.exp(x)
            return complex(r * c, r * s)
        else:
            return complex(NAN, NAN)
    elif math.isnan(x):
        if y:
            return complex(x, x)  # nan + j nan
        else:
            return complex(x, y)  # nan + 0j
    elif x > 0.0:
        # x == +inf
        if y_is_finite:
            c = math.cos(y)
            s = math.sin(y)
            return complex(x * c, y * s)
        else:
            return complex(x, NAN)
    else:
        # x == -inf
        if y_is_finite:
            r = math.exp(x)
            c = math.cos(y)
            s = math.sin(y)
            return complex(r * c, r * s)
        else:
            return complex(r, r)

@register
@implement(cmath.log, types.Kind(types.Complex))
@intrinsic_complex_unary
def log_impl(x, y, x_is_finite, y_is_finite):
    """cmath.log(x + y j)"""
    a = math.log(math.hypot(x, y))
    b = math.atan2(y, x)
    return complex(a, b)


@register
@implement(cmath.log, types.Kind(types.Complex), types.Kind(types.Complex))
def log_base_impl(context, builder, sig, args):
    """cmath.log(z, base)"""
    [z, base] = args

    def log_base(z, base):
        return cmath.log(z) / cmath.log(base)

    return context.compile_internal(builder, log_base, sig, args)


@register
@implement(cmath.log10, types.Kind(types.Complex))
def log10_impl(context, builder, sig, args):
    LN_10 = 2.302585092994045684

    def log10_impl(z):
        """cmath.log10(z)"""
        z = cmath.log(z)
        # This formula gives better results on +/-inf than cmath.log(z, 10)
        # See http://bugs.python.org/issue22544
        return complex(z.real / LN_10, z.imag / LN_10)

    return context.compile_internal(builder, log10_impl, sig, args)


@register
@implement(cmath.phase, types.Kind(types.Complex))
@intrinsic_complex_unary
def phase_impl(x, y, x_is_finite, y_is_finite):
    """cmath.phase(x + y j)"""
    return math.atan2(y, x)

@register
@implement(cmath.polar, types.Kind(types.Complex))
@intrinsic_complex_unary
def polar_impl(x, y, x_is_finite, y_is_finite):
    """cmath.polar(x + y j)"""
    return math.hypot(x, y), math.atan2(y, x)


@register
@implement(cmath.sqrt, types.Kind(types.Complex))
def sqrt_impl(context, builder, sig, args):
    # We risk spurious overflow for components >= FLT_MAX / (1 + sqrt(2)).
    THRES = mathimpl.FLT_MAX / (1 + math.sqrt(2))

    def sqrt_impl(z):
        """cmath.sqrt(z)"""
        # This is NumPy's algorithm, see npy_csqrt() in npy_math_complex.c.src
        a = z.real
        b = z.imag
        if a == 0.0 and b == 0.0:
            return complex(abs(b), b)
        if math.isinf(b):
            return complex(abs(b), b)
        if math.isnan(a):
            return complex(a, a)
        if math.isinf(a):
            if a < 0.0:
                return complex(abs(b - b), math.copysign(a, b))
            else:
                return complex(a, math.copysign(b - b, b))

        # The remaining special case (b is NaN) is handled just fine by
        # the normal code path below.

        # Scale to avoid overflow
        if abs(a) >= THRES or abs(b) >= THRES:
            a *= 0.25
            b *= 0.25
            scale = True
        else:
            scale = False
        # Algorithm 312, CACM vol 10, Oct 1967
        if a >= 0:
            t = math.sqrt((a + math.hypot(a, b)) * 0.5)
            real = t
            imag = b / (2 * t)
        else:
            t = math.sqrt((-a + math.hypot(a, b)) * 0.5)
            real = abs(b) / (2 * t)
            imag = math.copysign(t, b)
        # Rescale
        if scale:
            return complex(real * 2, imag)
        else:
            return complex(real, imag)

    return context.compile_internal(builder, sqrt_impl, sig, args)


@register
@implement(cmath.cos, types.Kind(types.Complex))
def cos_impl(context, builder, sig, args):
    def cos_impl(z):
        """cmath.cos(z) = cmath.cosh(z j)"""
        return cmath.cosh(complex(-z.imag, z.real))

    return context.compile_internal(builder, cos_impl, sig, args)

@register
@implement(cmath.cosh, types.Kind(types.Complex))
def cosh_impl(context, builder, sig, args):
    def cosh_impl(z):
        """cmath.cosh(z)"""
        x = z.real
        y = z.imag
        if math.isinf(x):
            real = abs(x)
            if y == 0.0:
                # x = +inf, y = 0 => cmath.cosh(x + y j) = inf + 0j
                imag = y
            elif math.isnan(y):
                # x = +inf, y = NaN => cmath.cosh(x + y j) = inf + Nan * j
                imag = y
            elif y < 0.0:
                # x = +inf, y < 0 => cmath.cosh(x + y j) = inf - inf * j
                imag = -real
            else:
                # x = +inf, y > 0 => cmath.cosh(x + y j) = inf + inf * j
                imag = real
            if x < 0.0:
                # x = -inf => negate imaginary part of result
                imag = -imag
            return complex(real, imag)
        return complex(math.cos(y) * math.cosh(x),
                       math.sin(y) * math.sinh(x))

    return context.compile_internal(builder, cosh_impl, sig, args)


@register
@implement(cmath.sin, types.Kind(types.Complex))
def sin_impl(context, builder, sig, args):
    def sin_impl(z):
        """cmath.sin(z) = -j * cmath.sinh(z j)"""
        r = cmath.sinh(complex(-z.imag, z.real))
        return complex(r.imag, -r.real)

    return context.compile_internal(builder, sin_impl, sig, args)

@register
@implement(cmath.sinh, types.Kind(types.Complex))
def sinh_impl(context, builder, sig, args):
    def sinh_impl(z):
        """cmath.sinh(z)"""
        x = z.real
        y = z.imag
        if math.isinf(x):
            real = x
            if y == 0.0:
                # x = +/-inf, y = 0 => cmath.sinh(x + y j) = x + y * j
                imag = y
            elif math.isnan(y):
                # x = +/-inf, y = NaN => cmath.sinh(x + y j) = x + NaN * j
                imag = y
            elif y < 0.0:
                # x = +/-inf, y < 0 => cmath.cosh(x + y j) = x - inf * j
                imag = -abs(x)
            else:
                # x = +/-inf, y > 0 => cmath.cosh(x + y j) = x + inf * j
                imag = abs(x)
            return complex(real, imag)
        return complex(math.cos(y) * math.sinh(x),
                       math.sin(y) * math.cosh(x))

    return context.compile_internal(builder, sinh_impl, sig, args)


@register
@implement(cmath.tan, types.Kind(types.Complex))
def tan_impl(context, builder, sig, args):
    def tan_impl(z):
        """cmath.tan(z) = -j * cmath.tanh(z j)"""
        r = cmath.tanh(complex(-z.imag, z.real))
        return complex(r.imag, -r.real)

    return context.compile_internal(builder, tan_impl, sig, args)

@register
@implement(cmath.tanh, types.Kind(types.Complex))
def tanh_impl(context, builder, sig, args):
    def tanh_impl(z):
        """cmath.tanh(z)"""
        x = z.real
        y = z.imag
        if math.isinf(x):
            real = math.copysign(1., x)
            imag = math.copysign(0., y)
            return complex(real, imag)
        # This is CPython's algorithm (see c_tanh() in cmathmodule.c).
        # XXX how to force float constants into single precision?
        tx = math.tanh(x)
        ty = math.tan(y)
        cx = 1. / math.cosh(x)
        txty = tx * ty
        denom = 1. + txty * txty
        return complex(
            tx * (1. + ty * ty) / denom,
            ((ty / denom) * cx) * cx)

    return context.compile_internal(builder, tanh_impl, sig, args)


@register
@implement(cmath.acos, types.Kind(types.Complex))
def acos_impl(context, builder, sig, args):
    LN_4 = math.log(4)
    THRES = mathimpl.FLT_MAX / 4

    def acos_impl(z):
        """cmath.acos(z)"""
        # CPython's algorithm (see c_acos() in cmathmodule.c)
        if abs(z.real) > THRES or abs(z.imag) > THRES:
            # Avoid unnecessary overflow for large arguments
            # (also handles infinities gracefully)
            real = math.atan2(abs(z.imag), z.real)
            imag = math.copysign(
                math.log(math.hypot(z.real * 0.5, z.imag * 0.5)) + LN_4,
                -z.imag)
            return complex(real, imag)
        else:
            s1 = cmath.sqrt(complex(1. - z.real, -z.imag))
            s2 = cmath.sqrt(complex(1. + z.real, z.imag))
            real = 2. * math.atan2(s1.real, s2.real)
            imag = math.asinh(s2.real * s1.imag - s2.imag * s1.real)
            return complex(real, imag)

    return context.compile_internal(builder, acos_impl, sig, args)

@register
@implement(cmath.acosh, types.Kind(types.Complex))
def acosh_impl(context, builder, sig, args):
    LN_4 = math.log(4)
    THRES = mathimpl.FLT_MAX / 4

    def acosh_impl(z):
        """cmath.acosh(z)"""
        # CPython's algorithm (see c_acosh() in cmathmodule.c)
        if abs(z.real) > THRES or abs(z.imag) > THRES:
            # Avoid unnecessary overflow for large arguments
            # (also handles infinities gracefully)
            real = math.log(math.hypot(z.real * 0.5, z.imag * 0.5)) + LN_4
            imag = math.atan2(z.imag, z.real)
            return complex(real, imag)
        else:
            s1 = cmath.sqrt(complex(z.real - 1., z.imag))
            s2 = cmath.sqrt(complex(z.real + 1., z.imag))
            real = math.asinh(s1.real * s2.real + s1.imag * s2.imag)
            imag = 2. * math.atan2(s1.imag, s2.real)
            return complex(real, imag)
        # Condensed formula (NumPy)
        #return cmath.log(z + cmath.sqrt(z + 1.) * cmath.sqrt(z - 1.))

    return context.compile_internal(builder, acosh_impl, sig, args)

@register
@implement(cmath.asinh, types.Kind(types.Complex))
def asinh_impl(context, builder, sig, args):
    LN_4 = math.log(4)
    THRES = mathimpl.FLT_MAX / 4

    def asinh_impl(z):
        """cmath.asinh(z)"""
        # CPython's algorithm (see c_asinh() in cmathmodule.c)
        if abs(z.real) > THRES or abs(z.imag) > THRES:
            real = math.copysign(
                math.log(math.hypot(z.real * 0.5, z.imag * 0.5)) + LN_4,
                z.real)
            imag = math.atan2(z.imag, abs(z.real))
            return complex(real, imag)
        else:
            s1 = cmath.sqrt(complex(1. + z.imag, -z.real))
            s2 = cmath.sqrt(complex(1. - z.imag, z.real))
            real = math.asinh(s1.real * s2.imag - s2.real * s1.imag)
            imag = math.atan2(z.imag, s1.real * s2.real - s1.imag * s2.imag)
            return complex(real, imag)

    return context.compile_internal(builder, asinh_impl, sig, args)

@register
@implement(cmath.asin, types.Kind(types.Complex))
def asin_impl(context, builder, sig, args):
    def asin_impl(z):
        """cmath.asin(z) = -j * cmath.asinh(z j)"""
        r = cmath.asinh(complex(-z.imag, z.real))
        return complex(r.imag, -r.real)

    return context.compile_internal(builder, asin_impl, sig, args)

@register
@implement(cmath.atan, types.Kind(types.Complex))
def atan_impl(context, builder, sig, args):
    def atan_impl(z):
        """cmath.atan(z) = -j * cmath.atanh(z j)"""
        r = cmath.atanh(complex(-z.imag, z.real))
        return complex(r.imag, -r.real)

    return context.compile_internal(builder, atan_impl, sig, args)

@register
@implement(cmath.atanh, types.Kind(types.Complex))
def atanh_impl(context, builder, sig, args):
    LN_4 = math.log(4)
    THRES_LARGE = math.sqrt(mathimpl.FLT_MAX / 4)
    THRES_SMALL = math.sqrt(mathimpl.FLT_MIN)
    PI_12 = math.pi / 2

    def atanh_impl(z):
        """cmath.atanh(z)"""
        # CPython's algorithm (see c_atanh() in cmathmodule.c)
        if z.real < 0.:
            # Reduce to case where z.real >= 0., using atanh(z) = -atanh(-z).
            negate = True
            z = -z
        else:
            negate = False

        ay = abs(z.imag)
        if math.isnan(z.real) or z.real > THRES_LARGE or ay > THRES_LARGE:
            if math.isinf(z.imag):
                real = math.copysign(0., z.real)
            elif math.isinf(z.real):
                real = 0.
            else:
                # may be safe from overflow, depending on hypot's implementation...
                h = math.hypot(z.real * 0.5, z.imag * 0.5)
                real = z.real/4./h/h
            imag = -math.copysign(PI_12, -z.imag)
        elif z.real == 1. and ay < THRES_SMALL:
            # C99 standard says:  atanh(1+/-0.) should be inf +/- 0j
            if ay == 0.:
                real = INF
                imag = z.imag
            else:
                real = -math.log(math.sqrt(ay) /
                                 math.sqrt(math.hypot(ay, 2.)))
                imag = math.copysign(math.atan2(2., -ay) / 2, z.imag)
        else:
            sqay = ay * ay
            zr1 = 1 - z.real
            real = math.log1p(4. * z.real / (zr1 * zr1 + sqay)) * 0.25
            imag = -math.atan2(-2. * z.imag,
                               zr1 * (1 + z.real) - sqay) * 0.5

        if math.isnan(z.imag):
            imag = NAN
        if negate:
            return complex(-real, -imag)
        else:
            return complex(real, imag)

    return context.compile_internal(builder, atanh_impl, sig, args)