# -*- coding: utf-8 -*-
"""
***************************************************************************
*   Copyright (c) 2026                                                    *
*                                                                         *
*   This file is a supplement to the FreeCAD CAx development system.      *
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU Lesser General Public License (LGPL)    *
*   as published by the Free Software Foundation; either version 2 of     *
*   the License, or (at your option) any later version.                   *
***************************************************************************
"""

import math

from FreeCAD import Base
import Part

import FastenerBase


def _make_insert_envelope(inner_radius, length, outer_diameter, body_diameter):
    """Build the exact A/E/C envelope for a straight-wall SI insert."""

    outer_radius = outer_diameter / 2.0
    body_radius = body_diameter / 2.0

    top_band_end = -0.34 * length
    top_transition_end = -0.40 * length
    middle_relief_end = -0.48 * length
    lower_band_start = -0.52 * length
    lower_band_end = -0.82 * length
    lead_start = -0.90 * length

    face_maker = FastenerBase.FSFaceMaker()
    face_maker.AddPoints(
        (inner_radius, 0.0),
        (outer_radius, 0.0),
        (outer_radius, top_band_end),
        (body_radius, top_transition_end),
        (body_radius, middle_relief_end),
        (outer_radius, lower_band_start),
        (outer_radius, lower_band_end),
        (body_radius, lead_start),
        (body_radius, -length),
        (inner_radius, -length),
    )
    return face_maker.GetFace(), (
        (top_transition_end, -0.02 * length, False),
        (lead_start, lower_band_start, True),
    )


def _make_diagonal_knurl_cutter(
    outer_diameter,
    body_diameter,
    z_start,
    z_end,
    left_handed,
):
    """Create one robust bank of diagonal grooves for a knurl band."""

    outer_radius = outer_diameter / 2.0
    body_radius = body_diameter / 2.0
    band_height = abs(z_end - z_start)
    z_center = (z_start + z_end) / 2.0

    nominal_count = math.pi * outer_diameter / 0.55
    groove_count = max(12, 4 * int(round(nominal_count / 4.0)))
    tangential_pitch = math.pi * outer_diameter / groove_count
    groove_width = min(tangential_pitch * 0.42, band_height * 0.20)
    groove_angle = math.radians(32.0)
    groove_length = (
        band_height * 0.90 - groove_width * math.sin(groove_angle)
    ) / math.cos(groove_angle)
    groove_depth = outer_radius - body_radius + 0.08

    cutter = Part.makeBox(
        groove_depth,
        groove_width,
        groove_length,
        Base.Vector(
            body_radius - 0.02,
            -groove_width / 2.0,
            z_center - groove_length / 2.0,
        ),
    )
    cutter.rotate(
        Base.Vector(0.0, 0.0, z_center),
        Base.Vector(1.0, 0.0, 0.0),
        -32.0 if left_handed else 32.0,
    )

    cutters = []
    angular_step = 360.0 / groove_count
    for index in range(groove_count):
        item = cutter.copy()
        item.rotate(
            Base.Vector(0.0, 0.0, 0.0),
            Base.Vector(0.0, 0.0, 1.0),
            (index + 0.5) * angular_step,
        )
        cutters.append(item)
    return Part.makeCompound(cutters)


def _make_iso_internal_thread_cutter(
    nominal_diameter,
    pitch,
    length,
    left_handed,
):
    """Build an ideal ISO 68-1 internal-thread groove over the full insert."""

    major_radius = nominal_diameter / 2.0
    fundamental_height = math.sqrt(3.0) * pitch / 2.0
    root_radius = major_radius - 5.0 * fundamental_height / 8.0
    overlap = 0.01
    margin_z = min(0.001, pitch / 100.0)

    points = (
        Base.Vector(root_radius - overlap, 0.0, margin_z),
        Base.Vector(major_radius, 0.0, 7.0 * pitch / 16.0),
        Base.Vector(major_radius, 0.0, 9.0 * pitch / 16.0),
        Base.Vector(root_radius - overlap, 0.0, pitch - margin_z),
    )
    profile = Part.Wire(
        [
            Part.makeLine(points[0], points[1]),
            Part.makeLine(points[1], points[2]),
            Part.makeLine(points[2], points[3]),
            Part.makeLine(points[3], points[0]),
        ]
    )

    helix = Part.makeLongHelix(
        pitch,
        length + 2.0 * pitch,
        major_radius,
        0.0,
        left_handed,
    )
    helix.rotate(
        Base.Vector(0.0, 0.0, 0.0),
        Base.Vector(1.0, 0.0, 0.0),
        180.0,
    )

    sweep = Part.BRepOffsetAPI.MakePipeShell(helix)
    sweep.setFrenetMode(True)
    sweep.setTransitionMode(0)
    sweep.add(profile)
    if not sweep.isReady():
        raise RuntimeError("Failed to create the heat-set insert's internal thread")
    sweep.build()
    sweep.makeSolid()
    return sweep.shape(), root_radius


def makeStandardHeatInsert(self, fa):
    """Make a PennEngineering SI IUTA/IUTB/IUTC metric heat-set insert.

    The A, E, C, mounting-hole, and tolerance data come from the metric table
    on SI-6 of PennEngineering's SI Inserts For Plastics catalog:
    https://www.pemnet.com/wp-content/uploads/sites/9/2023/10/sidata.pdf

    The catalog does not specify knurl tooth pitch or the axial split between
    knurl bands, so those visual details are representative while the
    published envelope is exact.
    """

    pitch, outer_diameter, body_diameter, _hole_diameter = fa.dimTable[:4]
    length = FastenerBase.LenStr2Num(fa.calc_len)
    nominal_diameter = self.getDia(fa.calc_diam, True)
    fundamental_height = math.sqrt(3.0) * pitch / 2.0
    root_radius = nominal_diameter / 2.0 - 5.0 * fundamental_height / 8.0

    profile, knurl_bands = _make_insert_envelope(
        root_radius,
        length,
        outer_diameter,
        body_diameter,
    )
    insert = self.RevolveZ(profile)

    for z_start, z_end, left_handed in knurl_bands:
        insert = insert.cut(
            _make_diagonal_knurl_cutter(
                outer_diameter,
                body_diameter,
                z_start,
                z_end,
                left_handed,
            )
        )

    if fa.Thread:
        thread_cutter, _root_radius = _make_iso_internal_thread_cutter(
            nominal_diameter,
            pitch,
            length,
            fa.LeftHanded,
        )
        insert = insert.cut(thread_cutter)

    insert = insert.removeSplitter()
    if insert.isNull() or not insert.isValid() or len(insert.Solids) != 1:
        raise RuntimeError("Failed to build a valid heat-set insert solid")
    return insert
