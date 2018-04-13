import argparse
import collections
import os
import subprocess
import xml.etree.cElementTree as etree

import numpy as np
import gtar

from plato.cmap import cubeellipse_intensity

parser = argparse.ArgumentParser(
    description='Download a structure from the PDB and convert it to a file for visualization')
parser.add_argument('name',
    help='Structure name (i.e. 4hhb)')
parser.add_argument('--disable-cache',
    help='Don\'t use cached files')
parser.add_argument('--color-mode', default='sequence',
    help='Way to color particles')
parser.add_argument('--take-assembly', action='store_true',
    help='Take the self-assembly (large) structure')
parser.add_argument('--hetatm-keys', action='append', default=[],
    help='Take heteroatoms with particular given 3-letter keys')

atomic_radii = dict(
    C=1.7,
    N=1.55,
    O=1.52,
    S=1.8
)

def fetch_file(url, destination):
    cmd = ['wget', url, '-O', destination]
    subprocess.check_call(cmd)

def parse_xml(filename, color_mode):
    pdbx = lambda x: '{http://pdbml.pdb.org/schema/pdbx-v50.xsd}' + x

    positions = []
    colors = []
    diameters = []
    types = []

    tree = etree.parse(filename)

    atom_type_index_map = collections.defaultdict(lambda: len(atom_type_index_map))
    phi = (1 + np.sqrt(5))/2

    for particle in tree.iter(pdbx('atom_site')):
        coords = tuple(float(particle.find(pdbx('Cartn_{}'.format(coord))).text) for coord in 'xyz')

        atype = particle.find(pdbx('type_symbol')).text
        type_ = atom_type_index_map[atype]
        diameter = 2*atomic_radii.get(atype, 1)

        if color_mode == 'sequence':
            color = np.ones((4,), dtype=np.float32)
            theta = int(particle.find(pdbx('auth_seq_id')).text)*2*np.pi*(1 - 1/phi)
            color[:3] = cubeellipse_intensity(theta, h=1.7, s=-.5*np.pi/3, lam=.55)
        elif color_mode == 'element':
            color = np.ones((4,), dtype=np.float32)
            theta = atom_type_index_map[atype]*2*np.pi*(1 - 1/phi)
            color[:3] = cubeellipse_intensity(theta, h=1.7, s=-.5*np.pi/3, lam=.55)
        else:
            raise NotImplementedError('Unknown color mode {}'.format(color_mode))

        positions.append(coords)
        colors.append(color)
        diameters.append(diameter)
        types.append(type_)

    positions = np.array(positions, dtype=np.float32)
    positions -= np.mean(positions, axis=0, keepdims=True)

    box = (2*np.max(positions, axis=0) - 2*np.min(positions, axis=0)).tolist()
    box.extend([0, 0, 0])

    print('Found {} particles'.format(len(positions)))
    print('Found types: {}'.format(list(sorted(atom_type_index_map))))

    return (positions, box, colors, diameters, types)

def parse_pdb(filename, color_mode, hetatm_keys):
    hetatm_keys = set(hetatm_keys)

    cmd = ['gunzip', '-kf', filename]
    subprocess.check_call(cmd)

    filename = filename.replace('.gz', '')

    positions = []
    colors = []
    diameters = []
    types = []

    atom_type_index_map = collections.defaultdict(lambda: len(atom_type_index_map))
    phi = (1 + np.sqrt(5))/2
    unit_count = 0

    for line in open(filename, 'r'):
        if line.startswith('TER'):
            unit_count += 1

        if not (line.startswith('ATOM') or line.startswith('HETATM')):
            continue

        if line.startswith('HETATM'):
            key = line[17:20].strip()
            if key not in hetatm_keys:
                continue

        coords = tuple(map(float, (line[start:end] for (start, end) in
                                   [(26, 38), (38, 46), (46, 54)])))

        atype = line[76:78].strip()
        type_ = atom_type_index_map[atype]
        diameter = 2*atomic_radii.get(atype, 1)
        color_indices = []

        if color_mode == 'sequence':
            color = np.ones((4,), dtype=np.float32)
            color_indices.append(int(line[22:26]))
        elif color_mode == 'element':
            color_indices.append(atom_type_index_map[atype])
        elif color_mode == 'unit':
            color_indices.append(unit_count)
        else:
            raise NotImplementedError('Unknown color mode {}'.format(color_mode))

        color_thetas = np.array(color_indices)*2*np.pi*(1 - 1/phi)
        color = np.ones((len(color_thetas), 4), dtype=np.float32)
        color[:, :3] = cubeellipse_intensity(color_thetas, h=1.7, s=-.5*np.pi/3, lam=.55)

        positions.append(coords)
        colors.append(color)
        diameters.append(diameter)
        types.append(type_)

    positions = np.array(positions, dtype=np.float32)
    positions -= np.mean(positions, axis=0, keepdims=True)

    box = (2*np.max(positions, axis=0) - 2*np.min(positions, axis=0)).tolist()
    box.extend([0, 0, 0])

    print('Found {} particles'.format(len(positions)))
    print('Found types: {}'.format(list(sorted(atom_type_index_map))))

    return (positions, box, colors, diameters, types)

def main(name, disable_cache, color_mode, take_assembly, hetatm_keys):
    if take_assembly:
        url = 'https://files.rcsb.org/download/{}.pdb1.gz'.format(name)
        destination = '/tmp/{}.pdb1.gz'.format(name)
    else:
        url = 'https://files.rcsb.org/download/{}.xml'.format(name)
        destination = '/tmp/{}.xml'.format(name)

    if disable_cache or not os.path.exists(destination):
        fetch_file(url, destination)

    if url.endswith('.xml'):
        (positions, box, colors, diameters, types) = parse_xml(destination, color_mode)
    elif url.endswith('.pdb1.gz'):
        (positions, box, colors, diameters, types) = parse_pdb(destination, color_mode, hetatm_keys)
    else:
        raise RuntimeError('Failed to parse any file, coder error')

    with gtar.GTAR('{}.zip'.format(name), 'w') as traj:
        traj.writePath('position.f32.ind', positions)
        traj.writePath('diameter.f32.ind', diameters)
        traj.writePath('color.f32.ind', colors)
        traj.writePath('type.u32.ind', np.zeros((len(positions),), dtype=np.uint32))
        traj.writePath('box.f32.uni', box)

if __name__ == '__main__': main(**vars(parser.parse_args()))
