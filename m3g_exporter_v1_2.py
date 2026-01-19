# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

bl_info = {
    "name": "M3G Exporter (.m3g)",
    "author": "Pierre Schiller - 3dcinetv",
    "version": (1, 2, 0),
    "blender": (3, 6, 0),
    "location": "File > Export > M3G (.m3g)",
    "description": "Export scenes to Mobile 3D Graphics format (JSR-184 v1.0/v1.1) for J2ME devices",
    "warning": "Fog export (v1.1) cannot be verified in most desktop viewers, use a Java environment",
    "doc_url": "https://github.com/3dcinetv/M3G-Blender-Exporter",
    "tracker_url": "https://github.com/3dcinetv/M3G-Blender-Exporter/issues",
    "category": "Import-Export",
}

import bpy
import os
import struct
import math
from array import array
from mathutils import Vector, Matrix, Euler, Quaternion
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator, Panel

# ---- Helper Functions -------------------------------------------------------#
def copy_file(source, dest):
    with open(source, 'rb') as file:
        data = file.read()
    with open(dest, 'wb') as file:
        file.write(data)

def toJavaBoolean(aValue):
    return 'true' if aValue else 'false'

def linear_to_srgb(linear):
    """Convert a linear color value to sRGB."""
    if linear <= 0.0031308:
        return linear * 12.92
    else:
        return 1.055 * (linear ** (1.0 / 2.4)) - 0.055

def linear_to_srgb_color(color):
    """Convert an RGB tuple from linear to sRGB color space."""
    return (
        linear_to_srgb(color[0]),
        linear_to_srgb(color[1]),
        linear_to_srgb(color[2])
    )

def sign(a):
    if a < 0: return -1
    elif a > 0: return 1
    else: return 0

def quaternion_to_axis_angle(quat):
    """Convert quaternion to axis-angle representation for M3G"""
    quat = quat.normalized()
    angle = 2.0 * math.acos(min(1.0, abs(quat.w)))
    
    if angle > 0.0001:
        s = math.sqrt(1.0 - quat.w * quat.w)
        if s < 0.001:
            s = 1.0
        axis_x = quat.x / s
        axis_y = quat.y / s
        axis_z = quat.z / s
    else:
        axis_x = 0.0
        axis_y = 0.0
        axis_z = 1.0
        angle = 0.0
    
    return [angle, axis_x, axis_y, axis_z]

def doSearchDeep(inList, outList):
    for element in inList:
        if element is not None: 
            outList = element.searchDeep(outList)
    return outList

def getId(aObject):
    return 0 if aObject is None else aObject.id

# ---- M3G Types --------------------------------------------------------------#
class M3GVertexList:
    def __init__(self, wrapList):
        self.mlist = wrapList

    def __getitem__(self, key):
        item = self.mlist[key]
        if isinstance(item, bpy.types.MeshVertex):
            return (item.co[0], item.co[1], item.co[2])
        else:
            return item

class M3GBoneReference:
    def __init__(self, first, count):
        self.firstVertex = first
        self.vertexCount = count
        
class M3GBone:
    def __init__(self):
        self.verts = []
        self.transformNode = None
        self.references = []
        self.weight = 0

    def setVerts(self, aVerts):
        self.verts = aVerts
        self.createReferences()
        
    def createReferences(self):
        if len(self.verts) == 0: 
            return
        self.verts.sort()
        ref = []
        list = []
        last = self.verts[0]-1
        
        for vert in self.verts:
            if vert == last+1:
                list.append(vert)
            else:
                if len(list) > 0:
                    ref.append(M3GBoneReference(list[0], len(list)))
                list = [vert]
            last = vert
        
        if len(list) > 0:
            ref.append(M3GBoneReference(list[0], len(list)))
        self.references = ref

class M3GVector3D:
    def __init__(self, ax=0.0, ay=0.0, az=0.0):
        self.x = ax
        self.y = ay
        self.z = az
    
    def writeJava(self):
        return f"{self.x}f, {self.y}f, {self.z}f"
    
    def getData(self):
        return struct.pack("<3f", self.x, self.y, self.z)
    
    def getDataLength(self):
        return struct.calcsize("<3f")

class M3GMatrix:
    def __init__(self):
        self.elements = 16 * [0.0]
        
    def identity(self):
        self.elements[0] = 1.0
        self.elements[5] = 1.0
        self.elements[10] = 1.0
        self.elements[15] = 1.0
    
    def getData(self):
        return struct.pack('<16f', *self.elements)

    def getDataLength(self):
        return struct.calcsize('<16f')

class M3GColorRGB:
    def __init__(self, ared=0, agreen=0, ablue=0):
        self.red = ared
        self.green = agreen
        self.blue = ablue
        
    def writeJava(self):
        return f"0x00{self.red:02X}{self.green:02X}{self.blue:02X}"
    
    def getData(self):
        return struct.pack('3B', self.red, self.green, self.blue)
    
    def getDataLength(self):
        return struct.calcsize('3B')

class M3GColorRGBA:
    def __init__(self, ared=0, agreen=0, ablue=0, aalpha=0):
        self.red = ared
        self.green = agreen
        self.blue = ablue
        self.alpha = aalpha

    def writeJava(self):
        return f"0x{self.alpha:02X}{self.red:02X}{self.green:02X}{self.blue:02X}"
        
    def getData(self):
        return struct.pack('4B', self.red, self.green, self.blue, self.alpha)
    
    def getDataLength(self):
        return struct.calcsize('4B')

class M3GProxy:
    def __init__(self):
        self.name = ""
        self.id = 0
        self.ObjectType = 0
        self.binaryFormat = ''
        
    def __repr__(self):
        return f"<{self.__class__.__name__}:{self.name}:{self.id}>"

class M3GHeaderObject(M3GProxy):
    def __init__(self):
        super().__init__()
        self.M3GHeaderObject_binaryFormat = '<BBBII'
        self.ObjectType = 0
        self.id = 1
        self.VersionNumber = [2, 0] # M3G Version 2.0
        self.hasExternalReferences = False
        self.TotalFileSize = 0
        self.ApproximateContentSize = 0
        self.AuthoringField = 'Blender M3G Export'
    
    def getData(self):
        data = struct.pack(self.M3GHeaderObject_binaryFormat,
                           self.VersionNumber[0],
                           self.VersionNumber[1],
                           self.hasExternalReferences,
                           self.TotalFileSize,
                           self.ApproximateContentSize)
        author_bytes = self.AuthoringField.encode('utf-8') + b'\x00'
        data += author_bytes
        return data
    
    def getDataLength(self):
        value = struct.calcsize(self.M3GHeaderObject_binaryFormat)
        return value + len(self.AuthoringField.encode('utf-8')) + 1

class M3GExternalReference(M3GProxy):
    def __init__(self):         
        super().__init__()
        self.ObjectType = 0xFF
        self.URI = ''
        
    def getData(self):
        uri_bytes = self.URI.encode('utf-8') + b'\x00'
        return uri_bytes
        
    def getDataLength(self):
        return len(self.URI.encode('utf-8')) + 1
        
    def searchDeep(self, alist):
        if self not in alist: 
            alist.append(self)
        return alist
        
    def __repr__(self):
        return f"{super().__repr__()} ({self.URI})"

class M3GObject3D(M3GProxy):
    def __init__(self):
        super().__init__()
        self.userID = 0
        self.animationTracks = []
        self.userParameterCount = 0
        
    def searchDeep(self, alist):
        alist = doSearchDeep(self.animationTracks, alist)
        if self not in alist: 
            alist.append(self)
        return alist
        
    def getData(self):
        data = struct.pack('<I', self.userID)
        data += struct.pack('<I', len(self.animationTracks))
        for element in self.animationTracks:
            data += struct.pack('<I', getId(element))
        data += struct.pack('<I', self.userParameterCount)
        return data

    def getDataLength(self):
        value = struct.calcsize('<3I')
        if len(self.animationTracks) > 0: 
            value += struct.calcsize(f'<{len(self.animationTracks)}I')
        return value

    def writeJava(self, aWriter, aCreate):
        if aCreate: 
            pass
        if len(self.animationTracks) > 0:
            aWriter.write(2)
            for iTrack in self.animationTracks:
                aWriter.write(2, f"BL{self.id}.addAnimationTrack(BL{iTrack.id});")

class M3GTransformable(M3GObject3D):
    def __init__(self):
        super().__init__()
        self.hasComponentTransform = False
        self.translation = M3GVector3D(0, 0, 0)
        self.scale = M3GVector3D(1, 1, 1)
        self.orientationAngle = 0
        self.orientationAxis = M3GVector3D(0, 0, 0)
        self.hasGeneralTransform = False
        self.transform = M3GMatrix()
        self.transform.identity()

    def writeJava(self, aWriter, aCreate):
        if aCreate: 
            pass
        super().writeJava(aWriter, False)
        if self.hasGeneralTransform:
            aWriter.write(2, f"float[] BL{self.id}_matrix = {{")
            aWriter.writeList(self.transform.elements, 4, "f")
            aWriter.write(2, "};")
            aWriter.write(2)
            aWriter.write(2, f"Transform BL{self.id}_transform = new Transform();")
            aWriter.write(2, f"BL{self.id}_transform.set(BL{self.id}_matrix);")
            aWriter.write(2, f"BL{self.id}.setTransform(BL{self.id}_transform);")
            aWriter.write(2)
        if self.hasComponentTransform:
            aWriter.write(2, f"BL{self.id}.setTranslation({self.translation.writeJava()});")

    def getData(self):
        data = super().getData()
        data += struct.pack("<B", self.hasComponentTransform) 
        if self.hasComponentTransform:
            data += self.translation.getData()
            data += self.scale.getData() 
            data += struct.pack('<f', self.orientationAngle) 
            data += self.orientationAxis.getData()
        data += struct.pack("<B", self.hasGeneralTransform) 
        if self.hasGeneralTransform:
            data += self.transform.getData()
        return data
        
    def getDataLength(self):
        value = super().getDataLength()
        value += struct.calcsize("<B")
        if self.hasComponentTransform:
            value += self.translation.getDataLength() 
            value += self.scale.getDataLength() 
            value += struct.calcsize('<f') 
            value += self.orientationAxis.getDataLength()
        value += struct.calcsize("<B") 
        if self.hasGeneralTransform:
            value += self.transform.getDataLength()
        return value

class M3GNode(M3GTransformable):
    def __init__(self):
        super().__init__()
        self.blenderObj = None
        self.parentBlenderObj = None
        self.blenderMatrixWorld = None
        self.M3GNode_binaryFormat = '<BBBIB'
        self.enableRendering = True
        self.enablePicking = True
        self.alphaFactor = 255
        self.scope = 4294967295
        self.hasAlignment = False
        self.M3GNode_binaryFormat_2 = '<BBII'
        self.zTarget = 0
        self.yTarget = 0
        self.zReference = None
        self.yReference = None

    def getData(self):
        data = super().getData()
        data += struct.pack(self.M3GNode_binaryFormat, 
                           self.enableRendering, 
                           self.enablePicking,  
                           self.alphaFactor, 
                           self.scope,  
                           self.hasAlignment)
                            
        if self.hasAlignment:
            data += struct.pack(self.M3GNode_binaryFormat_2, 
                              self.zTarget,  
                              self.yTarget, 
                              getId(self.zReference),  
                              getId(self.yReference)) 
        return data
        
    def getDataLength(self):
        value = super().getDataLength() + struct.calcsize(self.M3GNode_binaryFormat)
        if self.hasAlignment:
            value += struct.calcsize(self.M3GNode_binaryFormat_2)
        return value
        
    def writeJava(self, aWriter, aCreate):
        if aCreate: 
            pass
        super().writeJava(aWriter, False)

class M3GGroup(M3GNode):
    def __init__(self):
        super().__init__()
        self.ObjectType = 9
        self.children = []
        
    def searchDeep(self, alist):
        for element in self.children:
            alist = element.searchDeep(alist)
        return super().searchDeep(alist)

    def writeJava(self, aWriter, aCreate):
        if aCreate:
            aWriter.write(2, f"//Group:{self.name}")
            aWriter.write(2, f"Group BL{self.id} = new Group();")
        super().writeJava(aWriter, False)
        for element in self.children:
            aWriter.write(2, f"BL{self.id}.addChild(BL{element.id});")
   
    def getData(self):
        data = super().getData()
        data += struct.pack("<I", len(self.children))
        for element in self.children:
            data += struct.pack("<I", getId(element))
        return data
    
    def getDataLength(self):
        return super().getDataLength() + struct.calcsize(f"<{len(self.children)+1}I")

class M3GWorld(M3GGroup):
    def __init__(self):
        super().__init__()
        self.ObjectType = 22
        self.activeCamera = None
        self.background = None
        self.M3GWorld_binaryFormat = '<II'
        
    def searchDeep(self, alist):
        alist = doSearchDeep([self.activeCamera, self.background], alist)
        return super().searchDeep(alist)

    def writeJava(self, aWriter, aCreate):
        if aCreate:
            aWriter.write(2, f"//World:{self.name}")
            aWriter.write(2, f"World BL{self.id} = new World();")
        super().writeJava(aWriter, False)
        if self.background is not None:
            aWriter.write(2, f"BL{self.id}.setBackground(BL{self.background.id});")
        if self.activeCamera is not None:
            aWriter.write(2, f"BL{self.id}.setActiveCamera(BL{self.activeCamera.id});")
        aWriter.write(2)

    def getData(self):
        data = super().getData()
        return data + struct.pack(self.M3GWorld_binaryFormat, getId(self.activeCamera), getId(self.background))

    def getDataLength(self):
        return super().getDataLength() + struct.calcsize(self.M3GWorld_binaryFormat)

class M3GBackground(M3GObject3D):
    def __init__(self):
        super().__init__()
        self.ObjectType = 4
        self.M3GBackground_binaryFormat = '<BBiiiiBB'
        self.backgroundColor = M3GColorRGBA(255, 255, 255, 255)
        self.backgroundImage = None
        self.backgroundImageModeX = 32
        self.backgroundImageModeY = 32
        self.cropX = 0
        self.cropY = 0
        self.cropWidth = 0
        self.cropHeight = 0
        self.depthClearEnabled = True
        self.colorClearEnabled = True

    def writeJava(self, aWriter, aCreate):
        if aCreate:
            aWriter.write(2, f"//Background:{self.name}")
            aWriter.write(2, f"Background BL{self.id} = new Background();")
        super().writeJava(aWriter, False)
        aWriter.write(2, f"BL{self.id}.setColor({self.backgroundColor.writeJava()});")
        aWriter.write(2, "")

    def getData(self):
        data = super().getData()
        data += self.backgroundColor.getData()
        data += struct.pack('<I', getId(self.backgroundImage))
        data += struct.pack(self.M3GBackground_binaryFormat, 
                           self.backgroundImageModeX, 
                           self.backgroundImageModeY,
                           self.cropX, 
                           self.cropY, 
                           self.cropWidth, 
                           self.cropHeight, 
                           self.depthClearEnabled,  
                           self.colorClearEnabled)
        return data
    
    def getDataLength(self):
        value = super().getDataLength()
        value += self.backgroundColor.getDataLength()
        value += struct.calcsize('<I')
        value += struct.calcsize(self.M3GBackground_binaryFormat)
        return value

class M3GFog(M3GObject3D):
    """M3G Fog object for atmospheric effects
    
    JSR-184 Spec Section 11.7:
    - ObjectType: 07
    - Superclass data: Object3D
    - ColorRGB color
    - Byte mode (LINEAR=80, EXPONENTIAL=81)
    - IF mode==EXPONENTIAL: Float32 density
    - ELSE IF mode==LINEAR: Float32 near, Float32 far
    """
    LINEAR = 32
    EXPONENTIAL = 33
    
    def __init__(self):
        super().__init__()
        self.ObjectType = 7
        self.color = M3GColorRGB(128, 128, 128)
        self.mode = M3GFog.LINEAR
        self.density = 1.0  # Used only for EXPONENTIAL mode
        self.near = 0.0     # Used only for LINEAR mode
        self.far = 100.0    # Used only for LINEAR mode
    
    def getData(self):
        """Serialize fog data per JSR-184 spec - conditional fields based on mode"""
        data = super().getData()
        # Pack ColorRGB (3 bytes) and mode (1 byte) together to avoid any alignment issues
        data += struct.pack('<4B', self.color.red, self.color.green, self.color.blue, self.mode)
        
        # Conditional serialization based on mode
        if self.mode == M3GFog.EXPONENTIAL:
            data += struct.pack('<f', self.density)
        else:  # LINEAR (default)
            data += struct.pack('<ff', self.near, self.far)
        
        return data
    
    def getDataLength(self):
        """Calculate data length - varies by mode"""
        value = super().getDataLength()
        value += self.color.getDataLength()  # ColorRGB = 3 bytes
        value += struct.calcsize('<B')  # mode = 1 byte
        
        if self.mode == M3GFog.EXPONENTIAL:
            value += struct.calcsize('<f')  # density = 4 bytes
        else:  # LINEAR
            value += struct.calcsize('<ff')  # near + far = 8 bytes
        
        return value
    
    def writeJava(self, aWriter, aCreate):
        if aCreate:
            aWriter.write(2, f"//Fog:{self.name}")
            aWriter.write(2, f"Fog BL{self.id} = new Fog();")
        
        if self.mode == M3GFog.EXPONENTIAL:
            aWriter.write(2, f"BL{self.id}.setMode(Fog.EXPONENTIAL);")
            aWriter.write(2, f"BL{self.id}.setDensity({self.density}f);")
        else:
            aWriter.write(2, f"BL{self.id}.setMode(Fog.LINEAR);")
            aWriter.write(2, f"BL{self.id}.setLinear({self.near}f, {self.far}f);")
        
        aWriter.write(2, f"BL{self.id}.setColor({self.color.writeJava()});")
        super().writeJava(aWriter, False)
        aWriter.write(2)

# END OF PART A - Continue with Part B for remaining scene object classes

# PART B - Scene Objects, Materials, Animation Classes
# This continues from Part A

class M3GCamera(M3GNode):
    GENERIC = 48
    PARALLEL = 49
    PERSPECTIVE = 50
    
    def __init__(self):
        super().__init__()
        self.ObjectType = 5
        self.projectionType = M3GCamera.PERSPECTIVE
        self.fovy = 45.0
        self.AspectRatio = 1.0
        self.near = 0.1
        self.far = 100.0
    
    def writeJava(self, aWriter, aCreate):
        if aCreate:
            aWriter.write(2, f"//Camera {self.name}")
            aWriter.write(2, f"Camera BL{self.id} = new Camera();")
        super().writeJava(aWriter, False)
        aWriter.write(2, f"BL{self.id}.setPerspective({self.fovy}f,")
        aWriter.write(4, "(float)aCanvas.getWidth()/(float)aCanvas.getHeight(),")
        aWriter.write(4, f"{self.near}f, {self.far}f);")              
        
    def getData(self):
        data = super().getData()
        data += struct.pack("B", self.projectionType)
        if self.projectionType == self.GENERIC:
            data += self.projectionMatrix.getData()
        else:
            data += struct.pack("<4f", self.fovy, self.AspectRatio, self.near, self.far)
        return data
    
    def getDataLength(self):
        value = super().getDataLength()
        value += struct.calcsize("B")
        if self.projectionType == self.GENERIC:
            value += self.projectionMatrix.getDataLength()
        else:
            value += struct.calcsize("<4f")
        return value

class M3GLight(M3GNode):
    def __init__(self):
        super().__init__()
        self.ObjectType = 12
        self.modes = {
            'AMBIENT': 128,
            'DIRECTIONAL': 129,
            'OMNI': 130,
            'SPOT': 131
        }
        self.attenuationConstant = 1.0
        self.attenuationLinear = 0.0
        self.attenuationQuadratic = 0.0
        self.color = M3GColorRGB(255, 255, 255)
        self.mode = self.modes['DIRECTIONAL']
        self.intensity = 1.0
        self.spotAngle = 45
        self.spotExponent = 0.0
    
    def writeJava(self, aWriter, aCreate):
        if aCreate:
            aWriter.write(2, f"//Light: {self.name}")
            aWriter.write(2, f"Light BL{self.id} = new Light();")
        aWriter.write(2, f"BL{self.id}.setMode({self.mode});")
        if self.mode in [self.modes['OMNI'], self.modes['SPOT']]:
            aWriter.write(2, f"BL{self.id}.setAttenuation({self.attenuationConstant}f, {self.attenuationLinear}f, {self.attenuationQuadratic}f);")
        aWriter.write(2, f"BL{self.id}.setColor({self.color.writeJava()});")
        aWriter.write(2, f"BL{self.id}.setIntensity({self.intensity}f);")
        if self.mode == self.modes['SPOT']:
            aWriter.write(2, f"BL{self.id}.setSpotAngle({self.spotAngle}f);")
            aWriter.write(2, f"BL{self.id}.setSpotExponent({self.spotExponent}f);")
        super().writeJava(aWriter, False)
        aWriter.write(2)
        
    def getData(self):
        data = super().getData()
        data += struct.pack("<fff", 
                          self.attenuationConstant,
                          self.attenuationLinear, 
                          self.attenuationQuadratic) 
        data += self.color.getData() 
        data += struct.pack("<Bfff", 
                          self.mode,
                          self.intensity, 
                          self.spotAngle, 
                          self.spotExponent)
        return data

    def getDataLength(self):
        value = super().getDataLength()
        value += self.color.getDataLength()
        value += struct.calcsize('<B6f')
        return value

class M3GMaterial(M3GObject3D):
    def __init__(self):
        super().__init__()
        self.ObjectType = 13
        self.ambientColor = M3GColorRGB(51, 51, 51)
        self.diffuseColor = M3GColorRGBA(204, 204, 204, 255)
        self.emissiveColor = M3GColorRGB(0, 0, 0)
        self.specularColor = M3GColorRGB(0, 0, 0)
        self.shininess = 0.0
        self.vertexColorTrackingEnabled = False

    def writeJava(self, aWriter, aCreate):
        if aCreate:
            aWriter.write(2, f"//Material: {self.name}")
            aWriter.write(2, f"Material BL{self.id} = new Material();")
        aWriter.write(2, f"BL{self.id}.setColor(Material.AMBIENT, {self.ambientColor.writeJava()});")
        aWriter.write(2, f"BL{self.id}.setColor(Material.SPECULAR, {self.specularColor.writeJava()});")
        aWriter.write(2, f"BL{self.id}.setColor(Material.DIFFUSE, {self.diffuseColor.writeJava()});")
        aWriter.write(2, f"BL{self.id}.setColor(Material.EMISSIVE, {self.emissiveColor.writeJava()});")
        aWriter.write(2, f"BL{self.id}.setShininess({self.shininess}f);")
        aWriter.write(2, f"BL{self.id}.setVertexColorTrackingEnable({toJavaBoolean(self.vertexColorTrackingEnabled)});")
        super().writeJava(aWriter, False)
        
    def getData(self):
        data = super().getData()
        data += self.ambientColor.getData()
        data += self.diffuseColor.getData()
        data += self.emissiveColor.getData()
        data += self.specularColor.getData()
        data += struct.pack('<fB', self.shininess, self.vertexColorTrackingEnabled)
        return data

    def getDataLength(self):
        value = super().getDataLength()
        value += self.ambientColor.getDataLength()
        value += self.diffuseColor.getDataLength()
        value += self.emissiveColor.getDataLength()
        value += self.specularColor.getDataLength()
        value += struct.calcsize('<fB')
        return value

class M3GVertexArray(M3GObject3D):
    def __init__(self, aNumComponents, aComponentSize, aAutoScaling=False, aUVMapping=False):
        super().__init__()
        self.ObjectType = 20
        self.blenderIndexes = {}
        self.autoscaling = aAutoScaling
        self.uvmapping = aUVMapping
        self.bias = [0.0, 0.0, 0.0] 
        self.scale = 1.0 
        self.componentSize = aComponentSize
        self.componentCount = aNumComponents
        self.encoding = 0
        self.vertexCount = 0
        if self.autoscaling:
            self.components = array('f')
        else:
            self.components = self.createComponentArray()

    def createComponentArray(self):
        return array('b') if self.componentSize == 1 else array('h')
            
    def useMaxPrecision(self, aBoundingBox):
        vertexList = M3GVertexList(aBoundingBox)
        first = vertexList[0]
        minimum = [first[0], first[1], first[2]]
        maximum = [first[0], first[1], first[2]]
        
        for element in vertexList:
            for i in range(3):
                if minimum[i] > element[i]: 
                    minimum[i] = element[i]
                if maximum[i] < element[i]: 
                    maximum[i] = element[i]
        
        lrange = [0, 0, 0]
        maxRange = 0.0
        
        for i in range(3):
            lrange[i] = maximum[i] - minimum[i]
            self.bias[i] = minimum[i] * 0.5 + maximum[i] * 0.5
            if lrange[i] > maxRange:
                maxRange = lrange[i]
                
        self.scale = maxRange / 65533.0

    def internalAutoScaling(self):
        if not self.autoscaling or self.components.typecode != "f":
            return
        
        # Step 1: Flip V coordinate FIRST if this is a UV array
        # JSR-184 spec: "The T texture coordinate and the texture image are both reversed"
        if self.uvmapping:
            for i in range(0, len(self.components), self.componentCount):
                self.components[i+1] = 1.0 - self.components[i+1]
        
        # Step 2: Find min/max for each component (now on flipped UVs)
        minimum = []
        maximum = []
        for i in range(self.componentCount):
            minimum.append(self.components[i])
            maximum.append(self.components[i])         
            
        for i in range(0, len(self.components), self.componentCount):
            for j in range(self.componentCount):
                if minimum[j] > self.components[i+j]: 
                    minimum[j] = self.components[i+j]
                if maximum[j] < self.components[i+j]: 
                    maximum[j] = self.components[i+j]
        
        # Step 3: Calculate range and bias
        lrange = [0] * self.componentCount
        maxRange = 0.0
        
        for i in range(self.componentCount):
            lrange[i] = maximum[i] - minimum[i]
            self.bias[i] = minimum[i] * 0.5 + maximum[i] * 0.5
            if lrange[i] > maxRange:
                maxRange = lrange[i]
        
        # Step 4: Calculate scale (with zero-protection)
        maxValue = (2 ** (8 * self.componentSize)) - 2.0
        
        if maxRange < 1e-10:
            self.scale = 1.0 / maxValue
        else:
            self.scale = maxRange / maxValue
        
        # Step 5: Quantize to integers
        oldArray = self.components
        self.components = self.createComponentArray()
        
        for i in range(0, len(oldArray), self.componentCount):
            for j in range(self.componentCount):
                element = int((oldArray[i+j] - self.bias[j]) / self.scale)
                if self.componentSize == 1:
                    element = max(-127, min(127, element))
                else:
                    element = max(-32767, min(32767, element))
                self.components.append(element)
                
    def writeJava(self, aWriter, aCreate):
        self.internalAutoScaling()
        if aCreate:
            aWriter.write(2, f"// VertexArray {self.name}")
            if self.componentSize == 1:
                aWriter.write(2, f"byte[] BL{self.id}_array = {{")
            else:
                aWriter.write(2, f"short[] BL{self.id}_array = {{")
            aWriter.writeList(self.components)
            aWriter.write(2, "};")
            aWriter.write(2)
            aWriter.write(2, f"VertexArray BL{self.id} = new VertexArray(BL{self.id}_array.length/{self.componentCount},{self.componentCount},{self.componentSize});")
            aWriter.write(2, f"BL{self.id}.set(0,BL{self.id}_array.length/{self.componentCount},BL{self.id}_array);")
        super().writeJava(aWriter, False)
        aWriter.write(2)
     
    def getData(self):
        self.internalAutoScaling()
        self.vertexCount = len(self.components) // self.componentCount
        data = super().getData()
        data += struct.pack('<3BH', self.componentSize,
                                 self.componentCount,
                                 self.encoding,
                                 self.vertexCount)
        componentType = "b" if self.componentSize == 1 else "h"
        for element in self.components:
            data += struct.pack(f'<{componentType}', element)
        return data
        
    def getDataLength(self):
        self.internalAutoScaling()
        value = super().getDataLength()
        value += struct.calcsize('<3BH')
        componentType = "b" if self.componentSize == 1 else "h"
        value += struct.calcsize(f'<{len(self.components)}{componentType}')
        return value
        
    def append(self, element, index=None):
        if isinstance(element, Vector):
            for i in range(3):
                value = int((element[i] - self.bias[i]) / self.scale)                 
                self.components.append(value)
        elif isinstance(element, bpy.types.MeshVertex):
            for i in range(3):
                value = int((element.co[i] - self.bias[i]) / self.scale)                 
                self.components.append(value)
            if index is not None:
                key = str(len(self.blenderIndexes))
                self.blenderIndexes[key] = index
        else:
            self.components.append(element)

class M3GVertexBuffer(M3GObject3D):
    def __init__(self):
        super().__init__()
        self.ObjectType = 21
        self.defaultColor = M3GColorRGBA(255, 255, 255, 255)
        self.positions = None
        self.positionBias = [0.0, 0.0, 0.0]
        self.positionScale = 1.0
        self.normals = None
        self.colors = None
        self.texCoordArrays = [] 
        self.texcoordArrayCount = 0

    def searchDeep(self, alist):
        if self.positions is not None: 
            alist = self.positions.searchDeep(alist)
        if self.normals is not None: 
            alist = self.normals.searchDeep(alist)
        if self.colors is not None: 
            alist = self.colors.searchDeep(alist)
        alist = doSearchDeep(self.texCoordArrays, alist)
        return super().searchDeep(alist)
    
    def setPositions(self, aVertexArray):
        self.positions = aVertexArray
        self.positionBias = aVertexArray.bias
        self.positionScale = aVertexArray.scale
    
    def writeJava(self, aWriter, aCreate):
        if aCreate:
            aWriter.write(2, f"//VertexBuffer{self.name}")
            aWriter.write(2, f"VertexBuffer BL{self.id} = new VertexBuffer();")
        aWriter.write(2, f"float BL{self.id}_Bias[] = {{ {self.positionBias[0]}f, {self.positionBias[1]}f, {self.positionBias[2]}f}};")
        aWriter.write(2, f"BL{self.id}.setPositions(BL{self.positions.id},{self.positionScale}f,BL{self.id}_Bias);")
        if self.normals:
            aWriter.write(2, f"BL{self.id}.setNormals(BL{self.normals.id});")
        
        lIndex = 0
        for iTexCoord in self.texCoordArrays:
            aWriter.write(2, f"float BL{self.id}_{lIndex}_TexBias[] = {{ {iTexCoord.bias[0]}f, {iTexCoord.bias[1]}f, {iTexCoord.bias[2]}f}};")
            aWriter.write(2, f"BL{self.id}.setTexCoords({lIndex},BL{iTexCoord.id},{iTexCoord.scale}f,BL{self.id}_{lIndex}_TexBias);")
            lIndex += 1
   
        super().writeJava(aWriter, False)
    
    def getData(self):
        self.texcoordArrayCount = len(self.texCoordArrays)
        data = super().getData()
        data += self.defaultColor.getData()
        data += struct.pack('<I4f3I', 
                          getId(self.positions),
                          self.positionBias[0],
                          self.positionBias[1],
                          self.positionBias[2],
                          self.positionScale,
                          getId(self.normals),
                          getId(self.colors),
                          self.texcoordArrayCount)
        for iTexCoord in self.texCoordArrays:
            data += struct.pack('<I', getId(iTexCoord))
            data += struct.pack('<ffff', 
                              iTexCoord.bias[0],
                              iTexCoord.bias[1],
                              iTexCoord.bias[2],
                              iTexCoord.scale)
        return data

    def getDataLength(self):
        value = super().getDataLength()
        value += self.defaultColor.getDataLength()
        value += struct.calcsize('<I4f3I')
        value += struct.calcsize('<Iffff') * len(self.texCoordArrays)
        return value

class M3GPolygonMode(M3GObject3D):
    CULL_BACK = 160
    CULL_FRONT = 161
    CULL_NONE = 162
    SHADE_FLAT = 164
    SHADE_SMOOTH = 165
    WINDING_CCW = 168
    WINDING_CW = 169
    
    def __init__(self):
        super().__init__()
        self.ObjectType = 8
        self.culling = M3GPolygonMode.CULL_BACK
        self.shading = M3GPolygonMode.SHADE_SMOOTH
        self.winding = M3GPolygonMode.WINDING_CCW
        self.twoSidedLightingEnabled = False
        self.localCameraLightingEnabled = False
        self.perspectiveCorrectionEnabled = False
        
    def writeJava(self, aWriter, aCreate):
        if aCreate:
            aWriter.write(2, f"//PolygonMode")
            aWriter.write(2, f"PolygonMode BL{self.id} = new PolygonMode();")
        aWriter.write(2, f"BL{self.id}.setCulling({self.culling});")
        aWriter.write(2, f"BL{self.id}.setShading({self.shading});")
        aWriter.write(2, f"BL{self.id}.setWinding({self.winding});")
        aWriter.write(2, f"BL{self.id}.setTwoSidedLightingEnable({toJavaBoolean(self.twoSidedLightingEnabled)});")
        aWriter.write(2, f"BL{self.id}.setLocalCameraLightingEnable({toJavaBoolean(self.localCameraLightingEnabled)});")
        aWriter.write(2, f"BL{self.id}.setPerspectiveCorrectionEnable({toJavaBoolean(self.perspectiveCorrectionEnabled)});")
        aWriter.write(2)
        super().writeJava(aWriter, False)
    
    def getData(self):
        data = super().getData()
        data += struct.pack('6B', 
                          self.culling,
                          self.shading,
                          self.winding,
                          self.twoSidedLightingEnabled, 
                          self.localCameraLightingEnabled, 
                          self.perspectiveCorrectionEnabled)
        return data

    def getDataLength(self):
        value = super().getDataLength()
        value += struct.calcsize('6B')
        return value

class M3GIndexBuffer(M3GObject3D):
    def __init__(self):
        super().__init__()

    def getData(self):
        return super().getData()
        
    def getDataLength(self):
        return super().getDataLength()
    
    def writeJava(self, aWriter, aCreate):
        super().writeJava(aWriter, False)

class M3GTriangleStripArray(M3GIndexBuffer):
    def __init__(self):
        super().__init__()
        self.ObjectType = 11 
        self.encoding = 128
        self.indices = []
        self.stripLengths = []

    def writeJava(self, aWriter, aCreate):
        if aCreate:
            aWriter.write(2, "//TriangleStripArray")
            aWriter.write(2, f"int[] BL{self.id}_stripLength ={{{','.join([str(element) for element in self.stripLengths])}}};")
            aWriter.write(2)
            aWriter.write(2, f"int[] BL{self.id}_Indices = {{")
            aWriter.write(2, f"{','.join([str(element) for element in self.indices])}}};")
            aWriter.write(2)
            aWriter.write(2, f"IndexBuffer BL{self.id}=new TriangleStripArray(BL{self.id}_Indices,BL{self.id}_stripLength);")
        super().writeJava(aWriter, False)
        aWriter.write(2)
     
    def getData(self):
        data = super().getData()
        data += struct.pack('<BI', self.encoding, len(self.indices))
        for element in self.indices:
            data += struct.pack('<I', element)
        data += struct.pack('<I', len(self.stripLengths))
        for element in self.stripLengths:
            data += struct.pack('<I', element)
        return data
    
    def getDataLength(self):
        value = super().getDataLength()
        value += struct.calcsize('<BI')
        if len(self.indices) > 0:
            value += struct.calcsize(f'<{len(self.indices)}I')
        value += struct.calcsize('<I')
        if len(self.stripLengths) > 0:
            value += struct.calcsize(f'<{len(self.stripLengths)}I')
        return value

# END OF PART B - Continue with Part C for Mesh, Animation, and Export classes

# PART C - Mesh, Textures, Animation Classes
# This continues from Part B

class M3GAppearance(M3GObject3D):
    def __init__(self):
        super().__init__()
        self.ObjectType = 3
        self.layer = 0
        self.compositingMode = None
        self.fog = None
        self.polygonMode = None
        self.material = None
        self.textures = []
        
    def searchDeep(self, alist):
        alist = doSearchDeep([
            self.compositingMode,
            self.fog,
            self.polygonMode,
            self.material
        ] + self.textures, alist)
        return super().searchDeep(alist)

    def getData(self):
        data = super().getData()
        data += struct.pack("<B5I", 
                          self.layer,
                          getId(self.compositingMode),
                          getId(self.fog), 
                          getId(self.polygonMode), 
                          getId(self.material), 
                          len(self.textures))
        for element in self.textures:
            data += struct.pack("<I", getId(element))
        return data
    
    def getDataLength(self):
        value = super().getDataLength()
        value += struct.calcsize("<B5I")
        if len(self.textures) > 0: 
            value += struct.calcsize(f"<{len(self.textures)}I")
        return value
        
    def writeJava(self, aWriter, aCreate):
        if aCreate:
            aWriter.write(2, "//Appearance")
            aWriter.write(2, f"Appearance BL{self.id} = new Appearance();")
        if self.compositingMode is not None:
            aWriter.write(2, f"BL{self.id}.setCompositingMode(BL{self.compositingMode.id});")
        if self.fog is not None:
            aWriter.write(2, f"BL{self.id}.setFog(BL{self.fog.id});")
        if self.polygonMode is not None:
            aWriter.write(2, f"BL{self.id}.setPolygonMode(BL{self.polygonMode.id});")
        if self.material is not None: 
            aWriter.write(2, f"BL{self.id}.setMaterial(BL{self.material.id});")
        
        i = 0
        for itexture in self.textures:
            aWriter.write(2, f"BL{self.id}.setTexture({i},BL{itexture.id});")
            i += 1
            
        super().writeJava(aWriter, False)
        aWriter.write(2)

class M3GTexture2D(M3GTransformable):
    WRAP_REPEAT = 241
    WRAP_CLAMP = 240
    FILTER_BASE_LEVEL = 208
    FILTER_LINEAR = 209
    FILTER_NEAREST = 210
    FUNC_ADD = 224
    FUNC_BLEND = 225
    FUNC_DECAL = 226
    FUNC_MODULATE = 227
    FUNC_REPLACE = 228

    def __init__(self, aImage):
        super().__init__()
        self.ObjectType = 17
        self.Image = aImage
        self.blendColor = M3GColorRGB(0, 0, 0)
        self.blending = M3GTexture2D.FUNC_MODULATE
        self.wrappingS = M3GTexture2D.WRAP_REPEAT
        self.wrappingT = M3GTexture2D.WRAP_REPEAT
        self.levelFilter = M3GTexture2D.FILTER_BASE_LEVEL
        self.imageFilter = M3GTexture2D.FILTER_NEAREST

    def searchDeep(self, alist):
        alist = doSearchDeep([self.Image], alist)
        return super().searchDeep(alist)

    def getData(self):
        data = super().getData()
        data += struct.pack('<I', getId(self.Image))
        data += self.blendColor.getData()
        data += struct.pack('5B',
                          self.blending,
                          self.wrappingS, 
                          self.wrappingT, 
                          self.levelFilter, 
                          self.imageFilter)
        return data
    
    def getDataLength(self):
        value = super().getDataLength()
        value += struct.calcsize('<I')
        value += self.blendColor.getDataLength()
        value += struct.calcsize('5B')
        return value
            
    def writeJava(self, aWriter, aCreate):
        if aCreate:
            aWriter.write(2, "//Texture2D")
            aWriter.write(2, f"Texture2D BL{self.id} = new Texture2D(BL{self.Image.id});")
        aWriter.write(2, f"BL{self.id}.setFiltering({self.levelFilter},{self.imageFilter});")
        aWriter.write(2, f"BL{self.id}.setWrapping({self.wrappingS},{self.wrappingT});")
        aWriter.write(2, f"BL{self.id}.setBlending({self.blending});")
        aWriter.write(2)
        super().writeJava(aWriter, False)

class ImageFactory:
    images = {}
    
    @classmethod
    def getImage(cls, image, externalReference):
        filename = bpy.path.abspath(image.filepath)
        
        if filename in cls.images:
            return cls.images[filename]
        elif externalReference:
            ext = os.path.splitext(filename)[1].lower()
            if ext != ".png":
                print(f"Warning: image file ends with {ext}. M3G specification only mandates PNG support.")

            image_ref = M3GExternalReference()
            image_ref.URI = os.path.basename(filename)
            cls.images[filename] = image_ref
        else:
            image_ref = M3GImage2D(image)
            cls.images[filename] = image_ref
        return image_ref

class M3GImage2D(M3GObject3D):
    ALPHA = 96
    LUMINANCE = 97
    LUMINANCE_ALPHA = 98
    RGB = 99
    RGBA = 100

    def __init__(self, aImage, aFormat=RGBA):
        super().__init__()
        self.ObjectType = 10
        self.image = aImage
        self.format = aFormat
        self.isMutable = False
        self.width, self.height = aImage.size
        self.palette = 0
        self.pixels = array('B')
        self.extractPixelsFromImage()

    def getData(self):
        data = super().getData()
        data += struct.pack('2B', self.format, self.isMutable)
        data += struct.pack('<2I', self.width, self.height)
        if not self.isMutable:
            data += struct.pack('<I', 0)
            
            if self.format == M3GImage2D.RGBA:
                data += struct.pack('<I', len(self.pixels))
                for pixel in self.pixels:
                    data += struct.pack('B', pixel)
        return data

    def getDataLength(self):
        value = super().getDataLength()
        value += struct.calcsize('2B')
        value += struct.calcsize('<2I')
        if not self.isMutable:
            value += struct.calcsize('<I')
            
            if self.format == M3GImage2D.RGBA:
                value += struct.calcsize('<I')
                value += struct.calcsize(f'{len(self.pixels)}B')
        return value
    
    def writeJava(self, aWriter, aCreate):
        if aCreate:
            lFileName = bpy.path.abspath(self.image.filepath)
            if not os.path.exists(lFileName):
                lFileName = os.path.join(os.path.dirname(bpy.data.filepath), os.path.basename(self.image.filepath))
            
            if not os.path.exists(lFileName):
                raise Exception(f'Image file not found: {lFileName}')
                
            lTargetFile = os.path.join(os.path.dirname(aWriter.filename), os.path.basename(self.image.filepath))   
            copy_file(lFileName, lTargetFile)
            
            aWriter.write(2, "//Image2D")
            aWriter.write(2, f"Image BL{self.id}_Image = null;")
            aWriter.write(2, "try {")
            aWriter.write(3, f'BL{self.id}_Image = Image.createImage("/{os.path.basename(self.image.filepath)}");')
            aWriter.write(2, "} catch (IOException e) {")
            aWriter.write(3, "e.printStackTrace();")
            aWriter.write(2, "}")
            aWriter.write(2, f"Image2D BL{self.id} = new Image2D(Image2D.RGBA,BL{self.id}_Image);")   
        aWriter.write(2)
        super().writeJava(aWriter, False)
        aWriter.write(2)
        
    def extractPixelsFromImage(self):
        pixels = self.image.pixels[:]
        for y in range(self.height):
            for x in range(self.width):
                idx = (y * self.width + x) * 4
                r = int(pixels[idx] * 255)
                g = int(pixels[idx+1] * 255)
                b = int(pixels[idx+2] * 255)
                a = int(pixels[idx+3] * 255)
                self.pixels.append(r)
                self.pixels.append(g)
                self.pixels.append(b)
                self.pixels.append(a)

class M3GAnimationController(M3GObject3D):
    def __init__(self):
        super().__init__()
        self.ObjectType = 1
        self.speed = 1.0
        self.weight = 1.0
        self.activeIntervalStart = 0
        self.activeIntervalEnd = 0
        self.referenceSequenceTime = 0.0
        self.referenceWorldTime = 0

    def writeJava(self, aWriter, aCreate):
        if aCreate:
            aWriter.writeClass("AnimationController", self)
            aWriter.write(2, f"AnimationController BL{self.id} = new AnimationController();")
        aWriter.write(2, f"BL{self.id}.setActiveInterval({self.activeIntervalStart}, {self.activeIntervalEnd});")
        super().writeJava(aWriter, False)
            
    def getData(self):
        data = super().getData()
        data += struct.pack("<ffiifi", 
                          self.speed,
                          self.weight,
                          self.activeIntervalStart,
                          self.activeIntervalEnd, 
                          self.referenceSequenceTime, 
                          self.referenceWorldTime)
        return data
        
    def getDataLength(self):
        value = super().getDataLength()
        return value + struct.calcsize("<ffiifi")

class M3GAnimationTrack(M3GObject3D):
    ALPHA = 256
    AMBIENT_COLOR = 257
    COLOR = 258
    CROP = 259
    DENSITY = 260
    DIFFUSE_COLOR = 261
    EMISSIVE_COLOR = 262
    FAR_DISTANCE = 263
    FIELD_OF_VIEW = 264
    INTENSITY = 265
    MORPH_WEIGHTS = 266
    NEAR_DISTANCE = 267
    ORIENTATION = 268
    PICKABILITY = 269
    SCALE = 270
    SHININESS = 271
    SPECULAR_COLOR = 272
    SPOT_ANGLE = 273
    SPOT_EXPONENT = 274
    TRANSLATION = 275
    VISIBILITY = 276

    def __init__(self, aSequence, aProperty):
        super().__init__()
        self.ObjectType = 2
        self.keyframeSequence = aSequence
        self.animationController = None
        self.propertyID = aProperty
    
    def getData(self):
        data = super().getData()
        data += struct.pack("<3I", 
                          getId(self.keyframeSequence),
                          getId(self.animationController),
                          self.propertyID)
        return data
        
    def getDataLength(self):
        value = super().getDataLength()
        return value + struct.calcsize("<3I")
            
    def writeJava(self, aWriter, aCreate):
        if aCreate:
            aWriter.writeClass("AnimationTrack", self)
            aWriter.write(2, f"AnimationTrack BL{self.id} = new AnimationTrack(BL{self.keyframeSequence.id},{self.propertyID});")
        aWriter.write(2, f"BL{self.id}.setController(BL{self.animationController.id});")
        super().writeJava(aWriter, False)
        
    def searchDeep(self, alist):
        alist = doSearchDeep([self.keyframeSequence, self.animationController], alist)
        return super().searchDeep(alist)

class M3GKeyframeSequence(M3GObject3D):
    CONSTANT = 192
    LINEAR = 176
    LOOP = 193
    SLERP = 177
    SPLINE = 178
    SQUAD = 179
    STEP = 180
        
    def __init__(self, aNumKeyframes, aNumComponents, aBlenderInterpolation, aM3GInterpolation=None):
        super().__init__()
        self.ObjectType = 19
        if aM3GInterpolation is not None:
            self.interpolation = aM3GInterpolation
        else:
            if aBlenderInterpolation == "CONSTANT":
                self.interpolation = self.STEP
            elif aBlenderInterpolation == "BEZIER":
                self.interpolation = self.SPLINE
            elif aBlenderInterpolation == "LINEAR":
                self.interpolation = self.LINEAR
            else:
                self.interpolation = self.LINEAR
                
        self.repeatMode = self.CONSTANT
        self.encoding = 0
        self.duration = 0
        self.validRangeFirst = 0
        self.validRangeLast = 0
        self.componentCount = aNumComponents
        self.keyframeCount = aNumKeyframes
        self.time = []
        self.vectorValue = []

    def beforeExport(self):
        for i in range(self.keyframeCount):
            for j in range(self.componentCount):
                if abs(self.vectorValue[i][j]) < 0.000001:
                    self.vectorValue[i][j] = 0.0
    
    def getData(self):
        self.beforeExport()
        data = super().getData()
        data += struct.pack("<3B5I",
                          self.interpolation, 
                          self.repeatMode,
                          self.encoding, 
                          self.duration, 
                          self.validRangeFirst, 
                          self.validRangeLast, 
                          self.componentCount,
                          self.keyframeCount) 
        for i in range(self.keyframeCount):
            data += struct.pack("<i", self.time[i])
            for j in range(self.componentCount):
                data += struct.pack("<f", self.vectorValue[i][j])
        return data

    def getDataLength(self):
        value = super().getDataLength()
        value += struct.calcsize("<3B5I")
        value += struct.calcsize("<i") * self.keyframeCount
        value += struct.calcsize("<f") * self.keyframeCount * self.componentCount
        return value
        
    def setRepeatMode(self, aBlenderMode):
        if aBlenderMode == "CONSTANT":
            self.repeatMode = self.CONSTANT
        elif aBlenderMode == "CYCLIC":
            self.repeatMode = self.LOOP
        else:
            print(f"Extrapolation mode {aBlenderMode} not supported!")

    def setKeyframe(self, aIndex, aTime, aVector):
        self.time.append(aTime)
        self.vectorValue.append(aVector)
            
    def writeJava(self, aWriter, aCreate):
        self.beforeExport()
        if aCreate:
            aWriter.writeClass("KeyframeSequence", self)
            aWriter.write(2, f"KeyframeSequence BL{self.id} = new KeyframeSequence({self.keyframeCount}, {self.componentCount}, {self.interpolation});")
            for i in range(len(self.time)):
                lLine = f"BL{self.id}.setKeyframe({i},{self.time[i]}, new float[] {{ {self.vectorValue[i][0]}f, {self.vectorValue[i][1]}f, {self.vectorValue[i][2]}f"
                if self.componentCount == 4:
                    lLine += f", {self.vectorValue[i][3]}f"
                lLine += "});"
                aWriter.write(2, lLine)
        aWriter.write(2, f"BL{self.id}.setDuration({self.duration});")
        aWriter.write(2, f"BL{self.id}.setRepeatMode({self.repeatMode});")
        super().writeJava(aWriter, False)

class M3GMesh(M3GNode):
    def __init__(self, aVertexBuffer=None, aIndexBuffer=[], aAppearance=[]):
        super().__init__()
        self.ObjectType = 14
        self.vertexBuffer = aVertexBuffer
        self.submeshCount = len(aIndexBuffer)
        self.indexBuffer = aIndexBuffer
        self.appearance = aAppearance

    def getData(self):
        data = super().getData()
        data += struct.pack('<2I', getId(self.vertexBuffer), self.submeshCount)
        for i in range(len(self.indexBuffer)):
            data += struct.pack('<2I', getId(self.indexBuffer[i]), getId(self.appearance[i]))
        return data
        
    def getDataLength(self):
        value = super().getDataLength()
        value += struct.calcsize('<2I')
        for i in range(len(self.indexBuffer)):
            value += struct.calcsize('<2I')
        return value
            
    def searchDeep(self, alist):
        alist = doSearchDeep([self.vertexBuffer] + self.indexBuffer + self.appearance, alist)
        return super().searchDeep(alist)
            
    def writeJava(self, aWriter, aCreate):
        self.writeBaseJava(aWriter, aCreate, "Mesh", "")
        
    def writeBaseJava(self, aWriter, aCreate, aClassName, aExtension):
        if aCreate:
            aWriter.writeClass(aClassName, self)
            if self.submeshCount > 1:
                aWriter.write(2, f"IndexBuffer[] BL{self.id}_indexArray = {{")
                aWriter.write(4, ",".join([f"BL{i.id}" for i in self.indexBuffer]))
                aWriter.write(2, "};")
                aWriter.write(2)
                aWriter.write(2, f"Appearance[] BL{self.id}_appearanceArray = {{")
                aWriter.write(4, ",".join([f"BL{i.id}" for i in self.appearance]))
                aWriter.write(2, "};")
                aWriter.write(2)
                aWriter.write(2, f"{aClassName} BL{self.id} = new {aClassName}(BL{self.vertexBuffer.id},BL{self.id}_indexArray,BL{self.id}_appearanceArray{aExtension});")
            else:
                aWriter.write(2, f"{aClassName} BL{self.id} = new {aClassName}(BL{self.vertexBuffer.id},BL{self.indexBuffer[0].id},BL{self.appearance[0].id}{aExtension});")
        super().writeJava(aWriter, False)
        aWriter.write(2)

class M3GSkinnedMesh(M3GMesh):
    def __init__(self, aVertexBuffer=None, aIndexBuffer=[], aAppearance=[]):
        super().__init__(aVertexBuffer, aIndexBuffer, aAppearance)
        self.ObjectType = 16
        self.skeleton = None
        self.bones = {}
        
    def searchDeep(self, alist):
        alist = doSearchDeep([self.skeleton], alist)
        return super().searchDeep(alist)

    def getBlenderIndexes(self):
        return self.vertexBuffer.positions.blenderIndexes
    
    def writeJava(self, aWriter, aCreate):
        self.writeBaseJava(aWriter, aCreate, "SkinnedMesh", f",BL{self.skeleton.id}")
        aWriter.write(2, "//Transforms")
        for bone in self.bones.values():
            for ref in bone.references:
                aWriter.write(2, f"BL{self.id}.addTransform(BL{bone.transformNode.id},{bone.weight},{ref.firstVertex},{ref.vertexCount});")
        aWriter.write(2)
        
    def getDataLength(self):
        value = super().getDataLength()
        value += struct.calcsize('<I')
        value += struct.calcsize('<I')
        for bone in self.bones.values():
            for ref in bone.references:
                value += struct.calcsize('<3Ii')
        return value
 
    def getData(self):
        data = super().getData()
        data += struct.pack('<I', getId(self.skeleton))
        count = 0
        for bone in self.bones.values(): 
            count += len(bone.references)
        data += struct.pack('<I', count)
        for bone in self.bones.values():
            for ref in bone.references:
                data += struct.pack('<I', getId(bone.transformNode))
                data += struct.pack('<2I', ref.firstVertex, ref.vertexCount)
                data += struct.pack('<i', bone.weight)
        return data

# END OF PART C - Continue with Part D for Translator and Export classes

## PART D - Translator Class (VERSION 3 - WITH BACKGROUND FIX & DEBUG)
# This continues from Part C
#
# FIXES IN THIS VERSION:
# 1. Background color now extracted from World's Background shader node (Blender 3.6+)
# 2. Falls back to world.color if no nodes, or grey default if no world
# 3. Added extensive debug print statements for troubleshooting
# 4. Light intensity debugging added

class M3GTranslator:
    def __init__(self, context):
        self.context = context
        self.world = None
        self.scene = None
        self.nodes = []
        self.fog = None  # Single shared fog object for all appearances
    
    def start(self):
        print("=" * 60)
        print("M3G Translation started... (PART D VERSION 3)")
        print("=" * 60)
        
        self.scene = self.context.scene
        
        # Validate NLA tracks before starting
        self.validate_all_nla_tracks()
        
        # Validate bone weights if option is enabled
        if self.context.scene.m3g_export_props.limitBoneWeights:
            self.check_and_limit_bone_weights()
        
        # Check for compositor usage
        if self.scene.use_nodes and self.scene.node_tree:
            print("WARNING: Compositor nodes will be ignored in M3G export")
        
        self.world = self.translateWorld(self.scene)
        
        for obj in self.scene.objects:
            if obj.type == 'CAMERA':
                self.translateCamera(obj)
            elif obj.type == 'MESH':
                self.translateMesh(obj)
            elif obj.type == 'LIGHT' and self.context.scene.m3g_export_props.lightingEnabled:
                self.translateLamp(obj)
            elif obj.type == 'EMPTY':
                self.translateEmpty(obj)
            else:
                print(f"Warning: Could not translate {obj.name} of type {obj.type}")
                
        self.translateParenting()
        
        # DEBUG: Print summary of what was exported
        print("=" * 60)
        print("EXPORT SUMMARY:")
        print(f"  Total nodes: {len(self.nodes)}")
        light_count = sum(1 for n in self.nodes if isinstance(n, M3GLight))
        mesh_count = sum(1 for n in self.nodes if isinstance(n, M3GMesh) or isinstance(n, M3GSkinnedMesh))
        camera_count = sum(1 for n in self.nodes if isinstance(n, M3GCamera))
        print(f"  Lights: {light_count}")
        print(f"  Meshes: {mesh_count}")
        print(f"  Cameras: {camera_count}")
        print(f"  World children: {len(self.world.children)}")
        if self.fog:
            fog_mode = "LINEAR" if self.fog.mode == M3GFog.LINEAR else "EXPONENTIAL"
            print(f"  Fog: {fog_mode} mode (shared across all appearances)")
        else:
            print(f"  Fog: None")
        print("=" * 60)
            
        print("M3G Translation finished.")
        return self.world
    
    def validate_all_nla_tracks(self):
        """Validate that no object has multiple active NLA tracks"""
        for obj in self.scene.objects:
            if obj.animation_data and obj.animation_data.nla_tracks:
                active_tracks = [t for t in obj.animation_data.nla_tracks if not t.mute]
                if len(active_tracks) > 1:
                    raise Exception(
                        f"ERROR: Object '{obj.name}' has {len(active_tracks)} active NLA tracks.\n"
                        f"M3G only supports single animation track.\n"
                        f"Please bake NLA tracks to single action:\n"
                        f"1. Select object '{obj.name}'\n"
                        f"2. Go to NLA Editor\n"
                        f"3. Edit → Bake Action\n"
                        f"4. Mute or delete extra NLA tracks"
                    )
    
    def check_and_limit_bone_weights(self):
        """Check all meshes for vertices with >3 bone influences"""
        meshes_to_fix = []
        
        for obj in self.scene.objects:
            if obj.type == 'MESH' and obj.vertex_groups:
                for vertex in obj.data.vertices:
                    if len(vertex.groups) > 3:
                        meshes_to_fix.append(obj)
                        break
        
        if meshes_to_fix:
            print(f"WARNING: {len(meshes_to_fix)} mesh(es) have vertices with >3 bone influences")
            for obj in meshes_to_fix:
                self.limit_bone_weights(obj)
    
    def limit_bone_weights(self, mesh_obj):
        """Limit vertex groups to max 3 influences per vertex"""
        MAX_INFLUENCES = 3
        vertices_modified = 0
        
        for vertex in mesh_obj.data.vertices:
            if len(vertex.groups) > MAX_INFLUENCES:
                vertices_modified += 1
                
                # Sort by weight descending
                sorted_groups = sorted(vertex.groups, key=lambda g: g.weight, reverse=True)
                
                # Keep top 3
                top_3 = sorted_groups[:MAX_INFLUENCES]
                
                # Normalize weights to sum to 1.0
                total_weight = sum(g.weight for g in top_3)
                if total_weight > 0:
                    for group in top_3:
                        group.weight /= total_weight
                
                # Remove excess groups
                for group in sorted_groups[MAX_INFLUENCES:]:
                    mesh_obj.vertex_groups[group.group].remove([vertex.index])
        
        if vertices_modified > 0:
            print(f"Limited {vertices_modified} vertices to 3 bone influences in '{mesh_obj.name}'")
        
        return vertices_modified
        
    def translateWorld(self, scene):
        """Translate Blender world/scene to M3G World.
        
        VERSION 3 FIX: Now properly extracts background color from:
        1. World's Background shader node (if use_nodes is True)
        2. World.color (if no nodes)
        3. Default grey (0.5, 0.5, 0.5) if no world
        """
        world = M3GWorld()
        world.name = "World"

        # --- BACKGROUND COLOR EXTRACTION (VERSION 3 FIX) ---
        print("[DEBUG] translateWorld: Extracting background color...")
        
        world_color_linear = (0.5, 0.5, 0.5)  # Default grey fallback
        blWorld = scene.world
        
        if blWorld is not None:
            print(f"[DEBUG]   World found: '{blWorld.name}'")
            print(f"[DEBUG]   use_nodes: {blWorld.use_nodes}")
            
            if blWorld.use_nodes and blWorld.node_tree:
                # Look for the Background shader node
                bg_node = next(
                    (n for n in blWorld.node_tree.nodes if n.type == 'BACKGROUND'), 
                    None
                )
                
                if bg_node:
                    # Get the Color input's default value
                    color_input = bg_node.inputs.get('Color')
                    if color_input:
                        world_color_linear = color_input.default_value[:3]
                        print(f"[DEBUG]   Found Background node, color: RGB({world_color_linear[0]:.3f}, {world_color_linear[1]:.3f}, {world_color_linear[2]:.3f})")
                    else:
                        print("[DEBUG]   Background node has no Color input, using fallback")
                else:
                    print("[DEBUG]   No Background node found in world nodes, using fallback")
                    # Try world.color as fallback even with nodes
                    world_color_linear = blWorld.color[:3]
                    print(f"[DEBUG]   Fallback to world.color: RGB({world_color_linear[0]:.3f}, {world_color_linear[1]:.3f}, {world_color_linear[2]:.3f})")
            else:
                # No nodes, use simple world.color
                world_color_linear = blWorld.color[:3]
                print(f"[DEBUG]   No nodes, using world.color: RGB({world_color_linear[0]:.3f}, {world_color_linear[1]:.3f}, {world_color_linear[2]:.3f})")
        else:
            print("[DEBUG]   No world found, using default grey")
            
        # Convert from linear to sRGB
        world_color_srgb = linear_to_srgb_color(world_color_linear)
        print(f"[DEBUG]   Converted to sRGB: RGB({world_color_srgb[0]:.4f}, {world_color_srgb[1]:.4f}, {world_color_srgb[2]:.4f})")
        
        # Convert to M3G format (0-255 range)
        world.background = M3GBackground()
        world.background.name = "Background"
        world.background.backgroundColor = M3GColorRGBA(
            int(world_color_srgb[0] * 255),
            int(world_color_srgb[1] * 255),
            int(world_color_srgb[2] * 255),
            255
        )
        
        print(f"[DEBUG]   Final background color: RGBA({world.background.backgroundColor.red}, "
              f"{world.background.backgroundColor.green}, {world.background.backgroundColor.blue}, "
              f"{world.background.backgroundColor.alpha})")
        # --- END BACKGROUND FIX ---
            
        # Ambient light
        if blWorld is not None:
            if (self.context.scene.m3g_export_props.createAmbientLight and 
                self.context.scene.m3g_export_props.lightingEnabled):
                lLight = M3GLight()
                lLight.name = "AmbientLight"
                lLight.mode = lLight.modes['AMBIENT']
                
                # Use the same world color we extracted, converted to sRGB
                ambient_color_srgb = linear_to_srgb_color(world_color_linear)
                
                lLight.color = M3GColorRGB(
                    int(min(ambient_color_srgb[0] * 255, 255)),
                    int(min(ambient_color_srgb[1] * 255, 255)),
                    int(min(ambient_color_srgb[2] * 255, 255))
                )
                
                lLight.intensity = 0.8  # Subtle fill light
                
                self.nodes.append(lLight)
                print(f"[DEBUG]   Created ambient light:")
                print(f"[DEBUG]     Color (sRGB): RGB({lLight.color.red}, {lLight.color.green}, {lLight.color.blue})")
                print(f"[DEBUG]     Intensity: {lLight.intensity}")
            
            # Fog - create once and store for reuse in appearances
            # NOTE: Blender 3.6+ hides use_mist from UI but property still exists
            # We only check exportFog option - mist settings (start/depth/falloff) are always available
            if self.context.scene.m3g_export_props.exportFog:
                print(f"[DEBUG]   Export Fog enabled, creating fog from mist settings...")
                print(f"[DEBUG]     Mist start: {blWorld.mist_settings.start}")
                print(f"[DEBUG]     Mist depth: {blWorld.mist_settings.depth}")
                print(f"[DEBUG]     Mist falloff: {blWorld.mist_settings.falloff}")
                self.fog = self.translateFog(scene)
                if self.fog:
                    print(f"[DEBUG]   Created shared fog object:")
                    print(f"[DEBUG]     Mode: {'LINEAR' if self.fog.mode == M3GFog.LINEAR else 'EXPONENTIAL'}")
                    if self.fog.mode == M3GFog.LINEAR:
                        print(f"[DEBUG]     Near: {self.fog.near}, Far: {self.fog.far}")
                    else:
                        print(f"[DEBUG]     Density: {self.fog.density}")
                    print(f"[DEBUG]     Color: RGB({self.fog.color.red}, {self.fog.color.green}, {self.fog.color.blue})")
                else:
                    print(f"[DEBUG]   WARNING: translateFog returned None!")
            else:
                print(f"[DEBUG]   Export Fog disabled, skipping fog creation")

        return world
    
    def translateFog(self, scene):
        """Extract fog from Blender world mist settings
        
        Blender mist_settings.falloff_type maps to M3G fog modes:
        - QUADRATIC -> EXPONENTIAL (density-based falloff)
        - LINEAR -> LINEAR (distance-based falloff)
        - INVERSE_QUADRATIC -> EXPONENTIAL (approximation)
        
        For LINEAR mode: near = mist.start, far = mist.start + mist.depth
        For EXPONENTIAL mode: density = 2.0 / mist.depth (approximation)
        """
        if not scene.world:
            return None
        
        mFog = M3GFog()
        mFog.name = "Fog"
        mist = scene.world.mist_settings
        
        # Map Blender mist falloff to M3G fog mode
        if mist.falloff == 'LINEAR':
            mFog.mode = M3GFog.LINEAR
            mFog.near = mist.start
            mFog.far = mist.start + mist.depth
            print(f"[DEBUG]   Fog mode: LINEAR (near={mFog.near}, far={mFog.far})")
        else:
            # QUADRATIC, INVERSE_QUADRATIC, or LINEAR_QUADRATIC -> use EXPONENTIAL
            mFog.mode = M3GFog.EXPONENTIAL
            # Approximate density from depth (2/depth gives reasonable results)
            mFog.density = 2.0 / max(mist.depth, 0.001)
            print(f"[DEBUG]   Fog mode: EXPONENTIAL (density={mFog.density})")
        
        # Fog color from world color (convert linear to sRGB)
        world_color_linear = scene.world.color[:3]
        fog_color_srgb = linear_to_srgb_color(world_color_linear)
        mFog.color = M3GColorRGB(
            int(min(fog_color_srgb[0] * 255, 255)),
            int(min(fog_color_srgb[1] * 255, 255)),
            int(min(fog_color_srgb[2] * 255, 255))
        )
         # DEBUG: Check for length mismatch
        print(f"[DEBUG]   Fog getData length: {len(mFog.getData())}")
        print(f"[DEBUG]   Fog getDataLength(): {mFog.getDataLength()}")
        return mFog
        
    def translateParenting(self):
        for iNode in self.nodes:
            if iNode.parentBlenderObj is None:
                self.world.children.append(iNode)
            else:
                for jNode in self.nodes:
                    if iNode.parentBlenderObj == jNode.blenderObj:
                        jNode.children.append(iNode)
                        lMatrix = self.calculateChildMatrix(iNode.blenderMatrixWorld, jNode.blenderMatrixWorld)
                        iNode.transform = self.translateMatrix(lMatrix)
                        iNode.hasGeneralTransform = True
                        break
                    
    def calculateChildMatrix(self, child, parent):
        return Matrix(child) @ Matrix(parent).inverted()
    
    def translateArmature(self, armature_obj, mesh_obj, aSkinnedMesh):
        print(f"Translating Armature: {armature_obj.name}")
        armature = armature_obj.data
        
        mGroup = M3GGroup()
        mGroup.name = armature_obj.name
        self.translateCore(armature_obj, mGroup)
        aSkinnedMesh.skeleton = mGroup
        mGroup.transform = self.translateMatrix(
            self.calculateChildMatrix(armature_obj.matrix_world, mesh_obj.matrix_world))
        mGroup.hasGeneralTransform = True
        
        # Bones
        for bone in armature.bones:
            mBone = M3GBone()
            mBone.transformNode = M3GGroup()
            mBone.transformNode.name = bone.name
            self.translateCore(bone, mBone.transformNode)
            
            if bone.parent:
                mBone.transformNode.transform = self.translateMatrix(
                    self.calculateChildMatrix(bone.matrix_local, bone.parent.matrix_local))
            else:
                mBone.transformNode.transform = self.translateMatrix(bone.matrix_local)
            
            mBone.transformNode.hasGeneralTransform = True
            mBone.weight = 255  # Full weight (0-255 range in M3G)
            aSkinnedMesh.bones[bone.name] = mBone
            
        # Build bone hierarchy
        rootBones = []
        for bone in armature.bones:
            mBone = aSkinnedMesh.bones[bone.name]
            if not bone.parent: 
                rootBones.append(mBone)
            if bone.children:
                for childBone in bone.children:
                    mChildBone = aSkinnedMesh.bones[childBone.name]
                    mBone.transformNode.children.append(mChildBone.transformNode)
                    
        for rbone in rootBones:
            aSkinnedMesh.skeleton.children.append(rbone.transformNode)
        
        # Vertex groups - Skinning
        if mesh_obj.vertex_groups:
            for boneName in aSkinnedMesh.bones.keys():
                if boneName not in mesh_obj.vertex_groups:
                    continue
                verts = []
                for i, v in enumerate(mesh_obj.data.vertices):
                    for g in v.groups:
                        if g.group == mesh_obj.vertex_groups[boneName].index and g.weight > 0.01:
                            verts.append(i)
                            break
                aSkinnedMesh.bones[boneName].setVerts(verts)
        
        # Animation
        self.translateAction(armature_obj, aSkinnedMesh)
        
    def translateAction(self, obj, aM3GObject):
        """Export single action animation - FIXED FOR BLENDER 3.6"""
        if not obj.animation_data or not obj.animation_data.action:
            return
        
        action = obj.animation_data.action
        print(f"Translating action: {action.name}")
        
        # Create animation controller
        mController = M3GAnimationController()
        
        # Set time range from scene
        start_frame = self.context.scene.frame_start
        end_frame = self.context.scene.frame_end
        time_per_frame = 1000.0 / self.context.scene.render.fps
        
        mController.activeIntervalStart = int(start_frame * time_per_frame)
        mController.activeIntervalEnd = int(end_frame * time_per_frame)
        
        # Translate F-Curves
        self.translateFCurves(action, aM3GObject, mController, end_frame)
    
    def translateFCurves(self, action, aM3GObject, aController, endFrame):
        """Translate F-Curves to M3G animation - COMPLETELY REWRITTEN"""
        time_per_frame = 1000.0 / self.context.scene.render.fps
        
        # Group F-Curves by data path
        fcurve_groups = {}
        for fcurve in action.fcurves:
            data_path = fcurve.data_path
            if data_path not in fcurve_groups:
                fcurve_groups[data_path] = {}
            fcurve_groups[data_path][fcurve.array_index] = fcurve
        
        # Process each animation type
        for data_path, curves in fcurve_groups.items():
            if 'location' in data_path:
                self.translateLocationCurves(curves, aM3GObject, aController, endFrame, time_per_frame)
            elif 'rotation_euler' in data_path:
                self.translateRotationEulerCurves(curves, aM3GObject, aController, endFrame, time_per_frame)
            elif 'rotation_quaternion' in data_path:
                self.translateRotationQuaternionCurves(curves, aM3GObject, aController, endFrame, time_per_frame)
            elif 'scale' in data_path:
                self.translateScaleCurves(curves, aM3GObject, aController, endFrame, time_per_frame)
    
    def translateLocationCurves(self, curves, aM3GObject, aController, endFrame, time_per_frame):
        """Translate location F-Curves"""
        if 0 not in curves or 1 not in curves or 2 not in curves:
            return
            
        # Get all keyframe times
        all_times = set()
        for curve in curves.values():
            for kf in curve.keyframe_points:
                all_times.add(int(kf.co[0]))
        
        if not all_times:
            return
            
        keyframes_sorted = sorted(list(all_times))
        interpolation = curves[0].keyframe_points[0].interpolation if curves[0].keyframe_points else "LINEAR"
        
        mSequence = M3GKeyframeSequence(len(keyframes_sorted), 3, interpolation)
        mSequence.name = "Translation"
        mSequence.duration = int(endFrame * time_per_frame)
        
        for i, frame in enumerate(keyframes_sorted):
            x = curves[0].evaluate(frame)
            y = curves[1].evaluate(frame)
            z = curves[2].evaluate(frame)
            # Apply axis conversion: Blender Z-up to M3G Y-up
            # (x, y, z) -> (x, z, -y)
            mSequence.setKeyframe(i, int(frame * time_per_frame), [x, z, -y])
        
        mSequence.validRangeFirst = 0
        mSequence.validRangeLast = len(keyframes_sorted) - 1
        
        mTrack = M3GAnimationTrack(mSequence, M3GAnimationTrack.TRANSLATION)
        mTrack.animationController = aController
        aM3GObject.animationTracks.append(mTrack)
    
    def translateRotationEulerCurves(self, curves, aM3GObject, aController, endFrame, time_per_frame):
        """Translate Euler rotation F-Curves to M3G quaternion orientation"""
        if 0 not in curves or 1 not in curves or 2 not in curves:
            return
            
        all_times = set()
        for curve in curves.values():
            for kf in curve.keyframe_points:
                all_times.add(int(kf.co[0]))
        
        if not all_times:
            return
            
        keyframes_sorted = sorted(list(all_times))
        
        # M3G orientation uses axis-angle, so we use SLERP interpolation
        mSequence = M3GKeyframeSequence(len(keyframes_sorted), 4, "LINEAR", M3GKeyframeSequence.SLERP)
        mSequence.name = "Orientation"
        mSequence.duration = int(endFrame * time_per_frame)
        
        for i, frame in enumerate(keyframes_sorted):
            rx = curves[0].evaluate(frame)
            ry = curves[1].evaluate(frame)
            rz = curves[2].evaluate(frame)
            
            # Convert Euler to quaternion
            euler = Euler((rx, ry, rz), 'XYZ')
            quat = euler.to_quaternion()
            
            # Apply axis conversion
            axis_conversion = Quaternion((0.7071068, -0.7071068, 0, 0))  # -90° around X
            converted_quat = axis_conversion @ quat
            
            # Convert to axis-angle for M3G
            axis_angle = quaternion_to_axis_angle(converted_quat)
            mSequence.setKeyframe(i, int(frame * time_per_frame), axis_angle)
        
        mSequence.validRangeFirst = 0
        mSequence.validRangeLast = len(keyframes_sorted) - 1
        
        mTrack = M3GAnimationTrack(mSequence, M3GAnimationTrack.ORIENTATION)
        mTrack.animationController = aController
        aM3GObject.animationTracks.append(mTrack)
    
    def translateRotationQuaternionCurves(self, curves, aM3GObject, aController, endFrame, time_per_frame):
        """Translate Quaternion rotation F-Curves"""
        if 0 not in curves or 1 not in curves or 2 not in curves or 3 not in curves:
            return
            
        all_times = set()
        for curve in curves.values():
            for kf in curve.keyframe_points:
                all_times.add(int(kf.co[0]))
        
        if not all_times:
            return
            
        keyframes_sorted = sorted(list(all_times))
        
        mSequence = M3GKeyframeSequence(len(keyframes_sorted), 4, "LINEAR", M3GKeyframeSequence.SLERP)
        mSequence.name = "Orientation"
        mSequence.duration = int(endFrame * time_per_frame)
        
        for i, frame in enumerate(keyframes_sorted):
            w = curves[0].evaluate(frame)
            x = curves[1].evaluate(frame)
            y = curves[2].evaluate(frame)
            z = curves[3].evaluate(frame)
            
            quat = Quaternion((w, x, y, z))
            
            # Apply axis conversion
            axis_conversion = Quaternion((0.7071068, -0.7071068, 0, 0))
            converted_quat = axis_conversion @ quat
            
            axis_angle = quaternion_to_axis_angle(converted_quat)
            mSequence.setKeyframe(i, int(frame * time_per_frame), axis_angle)
        
        mSequence.validRangeFirst = 0
        mSequence.validRangeLast = len(keyframes_sorted) - 1
        
        mTrack = M3GAnimationTrack(mSequence, M3GAnimationTrack.ORIENTATION)
        mTrack.animationController = aController
        aM3GObject.animationTracks.append(mTrack)
    
    def translateScaleCurves(self, curves, aM3GObject, aController, endFrame, time_per_frame):
        """Translate scale F-Curves"""
        if 0 not in curves or 1 not in curves or 2 not in curves:
            return
            
        all_times = set()
        for curve in curves.values():
            for kf in curve.keyframe_points:
                all_times.add(int(kf.co[0]))
        
        if not all_times:
            return
            
        keyframes_sorted = sorted(list(all_times))
        interpolation = curves[0].keyframe_points[0].interpolation if curves[0].keyframe_points else "LINEAR"
        
        mSequence = M3GKeyframeSequence(len(keyframes_sorted), 3, interpolation)
        mSequence.name = "Scale"
        mSequence.duration = int(endFrame * time_per_frame)
        
        for i, frame in enumerate(keyframes_sorted):
            sx = curves[0].evaluate(frame)
            sy = curves[1].evaluate(frame)
            sz = curves[2].evaluate(frame)
            # Apply axis conversion for scale: (sx, sy, sz) -> (sx, sz, sy)
            mSequence.setKeyframe(i, int(frame * time_per_frame), [sx, sz, sy])
        
        mSequence.validRangeFirst = 0
        mSequence.validRangeLast = len(keyframes_sorted) - 1
        
        mTrack = M3GAnimationTrack(mSequence, M3GAnimationTrack.SCALE)
        mTrack.animationController = aController
        aM3GObject.animationTracks.append(mTrack)
    
    def translateShapeKeys(self, mesh_obj, m3gMesh):
        """Export shape keys as MORPH_WEIGHTS - NEW FEATURE"""
        if not self.context.scene.m3g_export_props.exportShapeKeys:
            return
        
        if not mesh_obj.data.shape_keys or not mesh_obj.data.shape_keys.key_blocks:
            return
        
        shape_keys = mesh_obj.data.shape_keys
        base_key = shape_keys.reference_key
        morph_targets = [k for k in shape_keys.key_blocks if k != base_key]
        
        if not morph_targets:
            return
        
        print(f"Exporting {len(morph_targets)} shape keys for {mesh_obj.name}")
        
        # Check if shape keys are animated
        if not shape_keys.animation_data or not shape_keys.animation_data.action:
            # Static shape keys - export current values
            print("Shape keys not animated, exporting static values")
            return
        
        action = shape_keys.animation_data.action
        time_per_frame = 1000.0 / self.context.scene.render.fps
        end_frame = self.context.scene.frame_end
        
        # Find all keyframes for shape keys
        all_keyframes = set()
        for fcurve in action.fcurves:
            if 'key_blocks' in fcurve.data_path:
                for kf in fcurve.keyframe_points:
                    all_keyframes.add(int(kf.co[0]))
        
        if not all_keyframes:
            return
        
        keyframes_sorted = sorted(list(all_keyframes))
        
        mSequence = M3GKeyframeSequence(
            len(keyframes_sorted),
            len(morph_targets),
            "LINEAR"
        )
        mSequence.name = "MorphWeights"
        mSequence.duration = int(end_frame * time_per_frame)
        
        for i, frame in enumerate(keyframes_sorted):
            weights = []
            for target in morph_targets:
                # Get weight at this frame
                fcurve = None
                for fc in action.fcurves:
                    if target.name in fc.data_path:
                        fcurve = fc
                        break
                
                if fcurve:
                    weight = fcurve.evaluate(frame)
                else:
                    weight = target.value
                
                weights.append(weight)
            
            mSequence.setKeyframe(i, int(frame * time_per_frame), weights)
        
        mSequence.validRangeFirst = 0
        mSequence.validRangeLast = len(keyframes_sorted) - 1
        
        mController = M3GAnimationController()
        mController.activeIntervalStart = int(self.context.scene.frame_start * time_per_frame)
        mController.activeIntervalEnd = int(end_frame * time_per_frame)
        
        mTrack = M3GAnimationTrack(mSequence, M3GAnimationTrack.MORPH_WEIGHTS)
        mTrack.animationController = mController
        m3gMesh.animationTracks.append(mTrack)
    
    def translateEmpty(self, obj):
        print(f"Translating empty: {obj.name}")
        mGroup = M3GGroup()
        self.translateToNode(obj, mGroup)
        
        # Translate object animation if present
        if obj.animation_data and obj.animation_data.action:
            self.translateAction(obj, mGroup)

# END OF PART D - Continue with Part E for remaining translation methods

# PART E - Mesh Translation, Materials, Cameras, Lights (VERSION 3 - MATERIAL FIX)
# This continues from Part D
#
# CRITICAL FIXES IN THIS VERSION:
# 1. translateMatrix() - Fixed row-major layout with translation in column 4 (indices 3,7,11)
# 2. Added Z-up to Y-up axis conversion for all object transforms
# 3. translateMaterials() - Now creates default fallback material when none exists
# 4. Default material: Teal RGB(44, 156, 184) - Windows 98 style!
# 5. vertexColorTrackingEnabled only set True when mesh has vertex colors
# 6. SHADE_SMOOTH (165) used for proper lighting
# 7. Extensive debug print statements added

    def translateCamera(self, obj):
        print(f"Translating camera: {obj.name}")
        camera = obj.data
        if camera.type != 'PERSP':
            print(f"Warning: Only perspective cameras are fully supported. Camera '{obj.name}' is {camera.type}")
            
        mCamera = M3GCamera()
        mCamera.projectionType = mCamera.PERSPECTIVE
        mCamera.fovy = camera.angle * 180.0 / 3.141592653589793
        mCamera.AspectRatio = self.context.scene.render.resolution_x / self.context.scene.render.resolution_y
        mCamera.near = camera.clip_start
        mCamera.far = camera.clip_end
        self.translateToNode(obj, mCamera)
        self.world.activeCamera = mCamera
        
        print(f"[DEBUG] Camera '{obj.name}': FOV={mCamera.fovy:.1f}, near={mCamera.near}, far={mCamera.far}")
        
        if obj.animation_data and obj.animation_data.action:
            self.translateAction(obj, mCamera)
    
# MATERIAL COLOR sRGB CONVERSION FIX
# Update the translateMaterials() method in PART E
#
# This fix converts material colors from Blender's linear space to sRGB
# so they match what you see in Blender's viewport.
#
# Find the section in translateMaterials() where colors are extracted from
# Principled BSDF and apply the linear_to_srgb_color() conversion.

# ============================================================================
# UPDATED translateMaterials method - Replace in PART E
# ============================================================================

    def translateMaterials(self, material, mesh, matIndex, createNormals, createUvs):
        """Translate Blender material to M3G Appearance.
        
        VERSION 4 FIXES:
        1. Always creates M3GMaterial for proper lighting (even if no Blender material)
        2. Default fallback color: Teal RGB(44, 156, 184)
        3. vertexColorTrackingEnabled only True when mesh has vertex colors
        4. Uses SHADE_SMOOTH (165) for proper shading
        5. NEW: Converts colors from Linear to sRGB to match Blender viewport
        """
        mAppearance = M3GAppearance()
        mAppearance.name = material.name if material else "DefaultMaterial"
        
        print(f"[DEBUG] translateMaterials: Processing '{mAppearance.name}'")
        print(f"[DEBUG]   createNormals={createNormals}, createUvs={createUvs}")
        print(f"[DEBUG]   material is None: {material is None}")
        
        # --- MATERIAL CREATION (VERSION 4 FIX) ---
        mMaterial = M3GMaterial()
        
        if material is not None:
            mMaterial.name = material.name
            print(f"[DEBUG]   Material found: '{material.name}'")
            print(f"[DEBUG]   use_nodes: {material.use_nodes}")
            
            if material.use_nodes:
                # Find Principled BSDF node
                bsdf = None
                for node in material.node_tree.nodes:
                    if node.type == 'BSDF_PRINCIPLED':
                        bsdf = node
                        break
                
                if bsdf:
                    print(f"[DEBUG]   Found Principled BSDF node")
                    
                    # Extract Base Color (LINEAR space in Blender)
                    base_color_input = bsdf.inputs.get('Base Color')
                    if base_color_input:
                        base_color_linear = base_color_input.default_value[:4]
                        print(f"[DEBUG]   Base Color (linear): RGBA({base_color_linear[0]:.3f}, {base_color_linear[1]:.3f}, {base_color_linear[2]:.3f}, {base_color_linear[3]:.3f})")
                        
                        # Convert to sRGB for export
                        base_color_srgb = linear_to_srgb_color(base_color_linear[:3])
                        print(f"[DEBUG]   Base Color (sRGB): RGB({base_color_srgb[0]:.3f}, {base_color_srgb[1]:.3f}, {base_color_srgb[2]:.3f})")
                        
                        # Diffuse color (main visible color) - use sRGB
                        mMaterial.diffuseColor = M3GColorRGBA(
                            int(min(base_color_srgb[0] * 255, 255)),
                            int(min(base_color_srgb[1] * 255, 255)),
                            int(min(base_color_srgb[2] * 255, 255)),
                            int(base_color_linear[3] * 255) if len(base_color_linear) > 3 else 255
                        )
                        
                        # Ambient color (~20% of diffuse for shadow depth) - use sRGB
                        mMaterial.ambientColor = M3GColorRGB(
                            int(min(base_color_srgb[0] * 51, 255)),  # ~20% of 255
                            int(min(base_color_srgb[1] * 51, 255)),
                            int(min(base_color_srgb[2] * 51, 255))
                        )
                    else:
                        print(f"[DEBUG]   No Base Color input found, using defaults")
                        mMaterial.diffuseColor = M3GColorRGBA(204, 204, 204, 255)
                        mMaterial.ambientColor = M3GColorRGB(51, 51, 51)
                    
                    # Extract Emission (also in linear space)
                    emission_input = bsdf.inputs.get('Emission Color')
                    if emission_input:
                        emission_linear = emission_input.default_value[:3]
                        emission_srgb = linear_to_srgb_color(emission_linear)
                        mMaterial.emissiveColor = M3GColorRGB(
                            int(min(emission_srgb[0] * 255, 255)),
                            int(min(emission_srgb[1] * 255, 255)),
                            int(min(emission_srgb[2] * 255, 255))
                        )
                        print(f"[DEBUG]   Emission (sRGB): RGB({emission_srgb[0]:.3f}, {emission_srgb[1]:.3f}, {emission_srgb[2]:.3f})")
                    else:
                        mMaterial.emissiveColor = M3GColorRGB(0, 0, 0)
                    
                    # Extract Roughness -> Shininess (not a color, no conversion needed)
                    roughness_input = bsdf.inputs.get('Roughness')
                    if roughness_input:
                        roughness = roughness_input.default_value
                        mMaterial.shininess = (1.0 - roughness) * 128.0
                        print(f"[DEBUG]   Roughness: {roughness:.3f} -> Shininess: {mMaterial.shininess:.1f}")
                    else:
                        mMaterial.shininess = 0.0
                    
                    # Specular color
                    specular_input = bsdf.inputs.get('Specular IOR Level')
                    if specular_input:
                        spec_val = specular_input.default_value
                        spec_intensity = int(min(spec_val * 128, 255))
                        mMaterial.specularColor = M3GColorRGB(spec_intensity, spec_intensity, spec_intensity)
                    else:
                        mMaterial.specularColor = M3GColorRGB(0, 0, 0)
                        
                else:
                    print(f"[DEBUG]   No Principled BSDF found, using fallback grey")
                    mMaterial.diffuseColor = M3GColorRGBA(204, 204, 204, 255)
                    mMaterial.ambientColor = M3GColorRGB(51, 51, 51)
                    mMaterial.emissiveColor = M3GColorRGB(0, 0, 0)
                    mMaterial.specularColor = M3GColorRGB(0, 0, 0)
                    mMaterial.shininess = 0.0
            else:
                # Non-node material (legacy)
                print(f"[DEBUG]   Non-node material, using diffuse_color")
                if hasattr(material, 'diffuse_color'):
                    dc_linear = material.diffuse_color[:3]
                    dc_srgb = linear_to_srgb_color(dc_linear)
                    mMaterial.diffuseColor = M3GColorRGBA(
                        int(min(dc_srgb[0] * 255, 255)),
                        int(min(dc_srgb[1] * 255, 255)),
                        int(min(dc_srgb[2] * 255, 255)),
                        255
                    )
                    mMaterial.ambientColor = M3GColorRGB(
                        int(min(dc_srgb[0] * 51, 255)),
                        int(min(dc_srgb[1] * 51, 255)),
                        int(min(dc_srgb[2] * 51, 255))
                    )
                else:
                    mMaterial.diffuseColor = M3GColorRGBA(204, 204, 204, 255)
                    mMaterial.ambientColor = M3GColorRGB(51, 51, 51)
                mMaterial.specularColor = M3GColorRGB(128, 128, 128)
                mMaterial.emissiveColor = M3GColorRGB(0, 0, 0)
                mMaterial.shininess = 0.0
        else:
            # --- NO MATERIAL: Use default fallback ---
            # Teal color: RGB(44, 156, 184) - Windows 98 style!
            # Note: This is already in sRGB, no conversion needed
            print(f"[DEBUG]   NO MATERIAL - Using default Teal fallback")
            mMaterial.name = "DefaultTealMaterial"
            mMaterial.diffuseColor = M3GColorRGBA(44, 156, 184, 255)  # Teal
            mMaterial.ambientColor = M3GColorRGB(9, 31, 37)  # ~20% of teal
            mMaterial.emissiveColor = M3GColorRGB(0, 0, 0)
            mMaterial.specularColor = M3GColorRGB(0, 0, 0)
            mMaterial.shininess = 0.0
        
        # --- VERTEX COLOR TRACKING ---
        has_vertex_colors = False
        if hasattr(mesh, 'vertex_colors') and mesh.vertex_colors and len(mesh.vertex_colors) > 0:
            has_vertex_colors = True
        if hasattr(mesh, 'color_attributes') and mesh.color_attributes and len(mesh.color_attributes) > 0:
            has_vertex_colors = True
            
        mMaterial.vertexColorTrackingEnabled = has_vertex_colors
        print(f"[DEBUG]   vertexColorTrackingEnabled: {has_vertex_colors}")
        
        # Debug output final material colors
        print(f"[DEBUG]   FINAL Material colors (sRGB):")
        print(f"[DEBUG]     Diffuse: RGBA({mMaterial.diffuseColor.red}, {mMaterial.diffuseColor.green}, {mMaterial.diffuseColor.blue}, {mMaterial.diffuseColor.alpha})")
        print(f"[DEBUG]     Ambient: RGB({mMaterial.ambientColor.red}, {mMaterial.ambientColor.green}, {mMaterial.ambientColor.blue})")
        print(f"[DEBUG]     Emissive: RGB({mMaterial.emissiveColor.red}, {mMaterial.emissiveColor.green}, {mMaterial.emissiveColor.blue})")
        print(f"[DEBUG]     Specular: RGB({mMaterial.specularColor.red}, {mMaterial.specularColor.green}, {mMaterial.specularColor.blue})")
        print(f"[DEBUG]     Shininess: {mMaterial.shininess}")
        
        # ALWAYS attach material to appearance for lighting to work
        mAppearance.material = mMaterial
        # --- END MATERIAL FIX ---

        # Texture handling
        if createUvs and material:
            lImage = None
            if material.use_nodes:
                for node in material.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image is not None:
                        lImage = node.image
                        break
            
            if lImage is not None:
                width, height = lImage.size
                powerWidth = 1
                while powerWidth < width:
                    powerWidth *= 2
                powerHeight = 1
                while powerHeight < height:
                    powerHeight *= 2
                
                if powerWidth != width or powerHeight != height:
                    print(f"WARNING: Texture '{lImage.name}' dimensions ({width}x{height}) are not power-of-two!")
                    print(f"M3G requires power-of-two textures. Texture will still be exported but may not display correctly.")
                
                mImage = ImageFactory.getImage(lImage, self.context.scene.m3g_export_props.textureExternal)
                mTexture = M3GTexture2D(mImage)
                mTexture.name = lImage.name
                mAppearance.textures.append(mTexture)
                # When texture is present, use white diffuse so texture shows at full brightness
                mMaterial.diffuseColor = M3GColorRGBA(255, 255, 255, 255)

        # --- POLYGON MODE ---
        mPolygonMode = M3GPolygonMode()
        mPolygonMode.name = "PolygonMode"
        mPolygonMode.perspectiveCorrectionEnabled = self.context.scene.m3g_export_props.perspectiveCorrection
        
        if hasattr(mesh, 'use_auto_smooth') and mesh.use_auto_smooth:
            mPolygonMode.culling = M3GPolygonMode.CULL_NONE
        else:
            mPolygonMode.culling = M3GPolygonMode.CULL_BACK
        
        if self.context.scene.m3g_export_props.smoothShading:
            mPolygonMode.shading = M3GPolygonMode.SHADE_SMOOTH  # 165
        else:
            mPolygonMode.shading = M3GPolygonMode.SHADE_FLAT    # 164
            
        print(f"[DEBUG]   PolygonMode: shading={mPolygonMode.shading} (165=SMOOTH, 164=FLAT), culling={mPolygonMode.culling}")
        
        mAppearance.polygonMode = mPolygonMode
        
        # Fog - use shared fog object created in translateWorld
        if self.fog is not None:
            mAppearance.fog = self.fog
        
        return mAppearance

    def translateMesh(self, obj):
        print(f"Translating mesh: {obj.name}")

        mesh = obj.data
        if len(mesh.polygons) <= 0:
            print(f"Empty mesh {obj.name} skipped")
            return
            
        vertexBuffer = M3GVertexBuffer()
        vertexBuffer.name = f"{obj.name}_VB"
        
        positions = M3GVertexArray(3, 2)
        positions.name = f"{obj.name}_Positions"
        
        if self.context.scene.m3g_export_props.autoscaling: 
            positions.useMaxPrecision(mesh.vertices)
            
        indexBuffers = []
        appearances = []
        
        createUvs = False
        if (self.context.scene.m3g_export_props.textureEnabled and 
            mesh.uv_layers.active is not None):
            for material in mesh.materials:
                if material is not None and material.use_nodes:
                    for node in material.node_tree.nodes:
                        if node.type == 'TEX_IMAGE':
                            createUvs = True
                            break
                    if createUvs:
                        break

        if createUvs:
            if self.context.scene.m3g_export_props.autoscaling:
                uvCoordinates = M3GVertexArray(2, 2, True, True)
                uvCoordinates.name = f"{obj.name}_UVs"
            else:
                uvCoordinates = M3GVertexArray(2, 2)
                uvCoordinates.name = f"{obj.name}_UVs"
                uvCoordinates.bias[0] = 0.5
                uvCoordinates.bias[1] = 0.5
                uvCoordinates.bias[2] = 0.5
                uvCoordinates.scale = 1.0 / 65535.0
        else:
            uvCoordinates = None

        # VERSION 3 FIX: Always create normals when lighting is enabled
        # This ensures proper shading even without explicit materials
        createNormals = self.context.scene.m3g_export_props.lightingEnabled
        print(f"[DEBUG] Mesh '{obj.name}': createNormals={createNormals}, createUvs={createUvs}")

        if createNormals:
            normals = M3GVertexArray(3, 1)
            normals.name = f"{obj.name}_Normals"
        else:
            normals = None
        
        # Process materials
        if len(mesh.materials) > 0:
            print(f"[DEBUG] Mesh has {len(mesh.materials)} material slot(s)")
            for materialIndex, material in enumerate(mesh.materials):
                faces = [face for face in mesh.polygons if face.material_index == materialIndex]
                if len(faces) > 0:
                    print(f"[DEBUG]   Material slot {materialIndex}: '{material.name if material else 'None'}' with {len(faces)} faces")
                    appearance = self.translateMaterials(material, mesh, materialIndex, createNormals, createUvs)
                    indexBuffer = self.translateFaces(faces, positions, normals, uvCoordinates, createNormals, createUvs, mesh)
                    indexBuffers.append(indexBuffer)
                    appearances.append(appearance)
        else:
            # NO MATERIALS: Use default appearance with fallback material
            print(f"[DEBUG] Mesh has NO materials - using default fallback")
            indexBuffer = self.translateFaces(mesh.polygons, positions, normals, uvCoordinates, createNormals, createUvs, mesh)
            indexBuffers.append(indexBuffer)
            # Pass None for material - translateMaterials will create default teal material
            appearance = self.translateMaterials(None, mesh, 0, createNormals, createUvs)
            appearances.append(appearance)

        vertexBuffer.setPositions(positions)
        if createNormals: 
            vertexBuffer.normals = normals
        if createUvs: 
            vertexBuffer.texCoordArrays.append(uvCoordinates)

        parent = obj.parent
        if parent is not None and parent.type == 'ARMATURE':
            mMesh = M3GSkinnedMesh(vertexBuffer, indexBuffers, appearances)
            self.translateArmature(parent, obj, mMesh)
        else:
            mMesh = M3GMesh(vertexBuffer, indexBuffers, appearances)
            
        self.translateToNode(obj, mMesh)
        
        if obj.animation_data and obj.animation_data.action:
            self.translateAction(obj, mMesh)
        
        self.translateShapeKeys(obj, mMesh)
        
# FIX FOR translateFaces() - N-GON SUPPORT
#
# The error "list assignment index out of range" happens because:
# - indices = [0, 0, 0, 0] only has 4 slots
# - Cylinder caps can have many more vertices (n-gons)
#
# Replace the translateFaces() method in PART E with this version:

    def translateFaces(self, faces, positions, normals, uvCoordinates, createNormals, createUvs, mesh):
        """Translates a list of faces into vertex data and triangle strips.
        
        VERSION 2 FIX: Now handles n-gons (faces with more than 4 vertices)
        by dynamically sizing the indices list.
        """
        triangleStrips = M3GTriangleStripArray()
        triangleStrips.name = f"{mesh.name}_Indices"
        
        uv_layer = mesh.uv_layers.active if createUvs else None
        
        for face in faces:
            # Dynamic indices list - sized to match face vertex count
            num_verts = len(face.vertices)
            indices = [0] * num_verts  # FIX: Dynamic size instead of fixed [0,0,0,0]
            
            for vertexIndex, vertex in enumerate(face.vertices):
                vertexCandidateIds = [int(k) for k, v in positions.blenderIndexes.items() if v == vertex]

                if createNormals and not face.use_smooth:
                    for candidateId in vertexCandidateIds[:]:
                        match = True
                        for j in range(3):
                            if abs(face.normal[j] * 127 - normals.components[candidateId * 3 + j]) > 0.5:
                                match = False
                                break
                        if not match:
                            vertexCandidateIds.remove(candidateId)

                if createUvs and uv_layer is not None:
                    uv_data = uv_layer.data[face.loop_indices[vertexIndex]].uv
                    print(f"[DEBUG UV] Face vertex {vertexIndex}: UV=({uv_data[0]:.4f}, {uv_data[1]:.4f})")
                    for candidateId in vertexCandidateIds[:]:
                        if self.context.scene.m3g_export_props.autoscaling:
                            s = uv_data[0]
                            t = uv_data[1]
                        else:
                            s = int((uv_data[0] - 0.5) * 65535)
                            t = int((0.5 - uv_data[1]) * 65535)
                        
                        if self.context.scene.m3g_export_props.autoscaling:
                            if (abs(s - uvCoordinates.components[candidateId * 2 + 0]) > 0.001 or 
                                abs(t - uvCoordinates.components[candidateId * 2 + 1]) > 0.001):
                                vertexCandidateIds.remove(candidateId)
                        else:
                            if (s != uvCoordinates.components[candidateId * 2 + 0] or 
                                t != uvCoordinates.components[candidateId * 2 + 1]):
                                vertexCandidateIds.remove(candidateId)

                if len(vertexCandidateIds) > 0:
                    indices[vertexIndex] = vertexCandidateIds[0]
                else:
                    positions.append(mesh.vertices[vertex], vertex)
                    indices[vertexIndex] = len(positions.components) // 3 - 1

                    if createNormals:
                        for j in range(3):
                            if face.use_smooth:
                                normals.append(int(mesh.vertices[vertex].normal[j] * 127))
                            else:
                                normals.append(int(face.normal[j] * 127))

                    if createUvs and uv_layer is not None:
                        uv_data = uv_layer.data[face.loop_indices[vertexIndex]].uv
                        if self.context.scene.m3g_export_props.autoscaling:
                            uvCoordinates.append(uv_data[0])
                            uvCoordinates.append(uv_data[1])
                        else:
                            uvCoordinates.append(int((uv_data[0] - 0.5) * 65535))
                            uvCoordinates.append(int((0.5 - uv_data[1]) * 65535))

            # Handle different face sizes
            # M3G uses triangle strips, so we need to convert polygons to triangles
            if num_verts == 3:
                # Triangle - add directly
                triangleStrips.stripLengths.append(3)
                triangleStrips.indices += [indices[0], indices[1], indices[2]]
            elif num_verts == 4:
                # Quad - convert to triangle strip (4 vertices = 2 triangles)
                triangleStrips.stripLengths.append(4)
                triangleStrips.indices += [indices[1], indices[2], indices[0], indices[3]]
            else:
                # N-gon (5+ vertices) - fan triangulation from first vertex
                # Creates (n-2) triangles, each as a separate strip of 3
                for i in range(1, num_verts - 1):
                    triangleStrips.stripLengths.append(3)
                    triangleStrips.indices += [indices[0], indices[i], indices[i + 1]]
                    
        return triangleStrips


# ============================================================================
# EXPLANATION:
# ============================================================================
#
# The original code had: indices = [0, 0, 0, 0]
# This only works for triangles (3 verts) and quads (4 verts)
#
# Cylinder caps in Blender are often n-gons with many vertices.
# For example, a 32-segment cylinder cap has 32 vertices!
#
# The fix:
# 1. indices = [0] * num_verts  - dynamically sized list
# 2. For n-gons (5+ verts): use fan triangulation
#    - Pick first vertex as the "fan center"
#    - Create triangles: (0,1,2), (0,2,3), (0,3,4), etc.
#
# This is a simple fan triangulation - works well for convex polygons
# like cylinder caps.
# ============================================================================
        
    def translateLamp(self, obj):
        """Translate Blender light to M3G Light.
        
        VERSION 3: Added debug output for light properties.
        """
        print(f"Translating light: {obj.name}")
        lamp = obj.data
        
        if lamp.type not in ['POINT', 'SPOT', 'SUN']:
            print(f"Warning: Light type {lamp.type} not fully supported")
            return
            
        mLight = M3GLight()
        if lamp.type == 'POINT':
            mLight.mode = mLight.modes['OMNI']  # 130
            mode_name = 'OMNI'
        elif lamp.type == 'SPOT':
            mLight.mode = mLight.modes['SPOT']
            mode_name = 'SPOT'
        elif lamp.type == 'SUN':
            mLight.mode = mLight.modes['DIRECTIONAL']
            mode_name = 'DIRECTIONAL'
            
        if lamp.type in ['POINT', 'SPOT']:
            mLight.attenuationConstant = 1.0
            # Blender 3.6 uses Watts for energy, need to normalize for M3G
            # M3G expects intensity as a multiplier (1.0 = normal)
            mLight.attenuationLinear = 0.0
            mLight.attenuationQuadratic = 0.0
            
        mLight.color = self.translateRGB(lamp.color)
        
        # --- INTENSITY FIX (VERSION 5) ---
        # M3G intensity is a multiplier where 1.0 = normal brightness
        # Blender 3.x uses physical units (Watts for point lights)
        # 
        # Standard conversion: 1000W Blender → 1.0 M3G intensity
        # This matches the JSR-184 expected range of ~0.0-2.0
        #
        # NOTE: HiCorp M3GViewer has a bug where POINT/OMNI lights
        # don't illuminate textured meshes. Use WizWorks or real
        # J2ME devices for accurate POINT light testing.
        
        if lamp.type == 'SUN':
            # Sun/Directional lights in Blender 3.x are in W/m²
            # Typically 1-10, so minor scaling
            mLight.intensity = lamp.energy
        else:
            # Point/Spot lights - normalize from Watts
            # 1000W (Blender default) → 1.0 M3G intensity
            mLight.intensity = lamp.energy / 1000.0
        
        # --- END INTENSITY FIX ---
        
        if lamp.type == 'SPOT':
            mLight.spotAngle = lamp.spot_size * 180.0 / 3.141592653589793 / 2.0
            mLight.spotExponent = lamp.spot_blend * 10.0
        
        # DEBUG OUTPUT
        print(f"[DEBUG] Light '{obj.name}':")
        print(f"[DEBUG]   Type: {lamp.type} -> M3G mode: {mode_name} ({mLight.mode})")
        print(f"[DEBUG]   Blender energy: {lamp.energy}")
        print(f"[DEBUG]   M3G intensity: {mLight.intensity}")
        print(f"[DEBUG]   Color: RGB({mLight.color.red}, {mLight.color.green}, {mLight.color.blue})")
        print(f"[DEBUG]   Attenuation: const={mLight.attenuationConstant}, linear={mLight.attenuationLinear}, quad={mLight.attenuationQuadratic}")
        if lamp.type == 'SPOT':
            print(f"[DEBUG]   Spot angle: {mLight.spotAngle}, exponent: {mLight.spotExponent}")
            
        self.translateToNode(obj, mLight)
        
        if obj.animation_data and obj.animation_data.action:
            self.translateAction(obj, mLight)

    def translateCore(self, obj, node):
        """Core translation for all node types"""
        node.name = obj.name
        node.userID = self.translateUserID(obj.name)
        
        if isinstance(obj, bpy.types.Bone):
            node.transform = self.translateMatrix(obj.matrix_local)
        else:
            node.transform = self.translateMatrix(obj.matrix_world)
        node.hasGeneralTransform = True
        
    def translateToNode(self, obj, node):
        """Translate Blender object to M3G node"""
        self.translateCore(obj, node)
        self.nodes.append(node)
        node.blenderObj = obj
        node.blenderMatrixWorld = obj.matrix_world
        
        lparent = None
        if obj.parent is not None:
            if obj.parent.type != 'ARMATURE':
                lparent = obj.parent
            else:
                if (obj.parent.parent is not None and 
                    obj.parent.parent.type != 'ARMATURE'):
                    lparent = obj.parent.parent
        node.parentBlenderObj = lparent
        
    def translateUserID(self, name):
        """Extract user ID from object name (e.g., 'Cube#42' -> 42)"""
        id = 0
        start = name.find('#')
        
        if start != -1:
            start += 1
            end = start
            for char in name[start:]:
                if char.isdigit():
                    end += 1
                else:
                    break
                    
            if end > start:
                id = int(name[start:end])
        
        return id
        
    def translateRGB(self, color):
        """Convert Blender RGB to M3G ColorRGB"""
        return M3GColorRGB(
            int(color[0] * 255),
            int(color[1] * 255), 
            int(color[2] * 255)
        )
    
    def translateRGBA(self, color, alpha):
        """Convert Blender RGBA to M3G ColorRGBA"""
        return M3GColorRGBA(
            int(color[0] * 255),
            int(color[1] * 255), 
            int(color[2] * 255),
            int(alpha * 255)
        )
    
    def translateMatrix(self, blenderMatrix):
        """Convert Blender matrix to M3G matrix.
        
        CRITICAL FIXES APPLIED:
        1. Matrix layout: M3G uses row-major with translation in column 4
           - Row 0 -> elements[0-3] with Tx at index 3
           - Row 1 -> elements[4-7] with Ty at index 7
           - Row 2 -> elements[8-11] with Tz at index 11
           - Row 3 -> elements[12-15] (0,0,0,1)
        
        2. Coordinate system conversion: Blender Z-up -> M3G Y-up
           - Apply -90 degree X rotation
           - This transforms: (X, Y, Z) -> (X, Z, -Y)
        
        The working Blender 2.49 exporter produced matrices like:
          [0.69, -0.32, 0.65, 7.48]   <- Tx at index 3
          [0.73, 0.31, -0.61, -6.51]  <- Ty at index 7
          [-0.01, 0.90, 0.45, 5.34]   <- Tz at index 11
          [0, 0, 0, 1]
        """
        # M3G coordinate system: Y-up, -Z forward (OpenGL style)
        # Blender coordinate system: Z-up, -Y forward
        #
        # Rotation matrix for -90° around X:
        # | 1   0   0   0 |
        # | 0   0   1   0 |
        # | 0  -1   0   0 |
        # | 0   0   0   1 |
        #
        axis_conversion = Matrix((
            (1.0,  0.0,  0.0, 0.0),
            (0.0,  0.0,  1.0, 0.0),
            (0.0, -1.0,  0.0, 0.0),
            (0.0,  0.0,  0.0, 1.0)
        ))
        
        # Apply axis conversion: convert Blender coords to M3G coords
        convertedMatrix = axis_conversion @ blenderMatrix
        
        # Now write in row-major order with translation in column 4
        # M3G expects: elements[0-3] = row 0, elements[4-7] = row 1, etc.
        lMatrix = M3GMatrix()
        
        # Row 0: [m00, m01, m02, m03(Tx)]
        lMatrix.elements[0] = convertedMatrix[0][0]
        lMatrix.elements[1] = convertedMatrix[0][1]
        lMatrix.elements[2] = convertedMatrix[0][2]
        lMatrix.elements[3] = convertedMatrix[0][3]  # Tx
        
        # Row 1: [m10, m11, m12, m13(Ty)]
        lMatrix.elements[4] = convertedMatrix[1][0]
        lMatrix.elements[5] = convertedMatrix[1][1]
        lMatrix.elements[6] = convertedMatrix[1][2]
        lMatrix.elements[7] = convertedMatrix[1][3]  # Ty
        
        # Row 2: [m20, m21, m22, m23(Tz)]
        lMatrix.elements[8] = convertedMatrix[2][0]
        lMatrix.elements[9] = convertedMatrix[2][1]
        lMatrix.elements[10] = convertedMatrix[2][2]
        lMatrix.elements[11] = convertedMatrix[2][3]  # Tz
        
        # Row 3: [0, 0, 0, 1]
        lMatrix.elements[12] = convertedMatrix[3][0]
        lMatrix.elements[13] = convertedMatrix[3][1]
        lMatrix.elements[14] = convertedMatrix[3][2]
        lMatrix.elements[15] = convertedMatrix[3][3]
        
        return lMatrix

# END OF PART E - Continue with Part F for Exporter and Writers

# PART F - Exporter, Writers, UI, Registration (VERSION 4 - WITH VERIFICATION)
# This continues from Part E
# 
# FIXES APPLIED:
# 1. TotalSectionLength = 13 + UncompressedLength (entire section size)
# 2. Version set to 1.0 (matching working Blender 2.49 export)
# 3. Object length uses actual data length

class M3GExporter:
    def __init__(self, context, aWriter): 
        self.context = context
        self.writer = aWriter

    def start(self):
        print("="*60)
        print("M3G Export Starting... (PART F VERSION 5 - FOG FIX)")
        print("="*60)
        
        Translator = M3GTranslator(self.context)
        world = Translator.start()
        
        exportList = self.createDeepSearchList(world)
        externalReferences = [element for element in exportList if isinstance(element, M3GExternalReference)]
        exportList = [element for element in exportList if not isinstance(element, M3GExternalReference)]
        
        i = 1
        
        for element in externalReferences:
            i += 1
            element.id = i
            print(f"External ref {element.id}: {element.name}")
            
        for element in exportList:
            i += 1
            element.id = i
            print(f"Object {element.id}: {element.ObjectType} - {element.name}")
            
        self.writer.writeFile(world, exportList, externalReferences)
        
        print("="*60)
        print("M3G Export Complete!")
        print("="*60)

    def createDeepSearchList(self, aWorld):
        return aWorld.searchDeep([])

class JavaWriter:
    def __init__(self, aFilename):
        self.filename = aFilename
        self.classname = os.path.basename(aFilename)
        self.classname = self.classname[:-5]
        self.outFile = open(aFilename, "w")
        
    def write(self, tab, zeile=""):
        print("\t" * tab + zeile, file=self.outFile)

    def writeFile(self, aWorld, aExportList, externalReferences):
        self.world = aWorld
        self.writeHeader()
        for element in aExportList:
            element.writeJava(self, True)
        self.writeFooter()
        self.outFile.close()
        
    def writeHeader(self):
        self.write(0, "import javax.microedition.lcdui.Image;")
        self.write(0, "import javax.microedition.m3g.*;")
        self.write(0, "import java.io.IOException;")
        self.write(0, f"public final class {self.classname} {{")
        self.write(1, "public static World getRoot(Canvas3D aCanvas) {")
          
    def writeFooter(self):
        self.write(1)
        self.write(1, f"return BL{self.world.id};")
        self.write(0, "}}")
        
    def writeList(self, alist, numberOfElementsPerLine=12, aType=""):
        line = ""
        lastLine = ""
        counter = 0
        for element in alist:
            if counter != 0:
                line = line + "," + str(element) + aType
            else:
                line = str(element) + aType
            counter += 1
            if counter == numberOfElementsPerLine:
                if len(lastLine) > 0:
                    self.write(3, lastLine + ",")
                lastLine = line
                line = ""
                counter = 0
        if len(lastLine) > 0:
            if len(line) > 0:
                self.write(3, lastLine + ",")
            else:
                self.write(3, lastLine)
        if len(line) > 0: 
            self.write(3, line)
    
    def writeClass(self, aName, aM3GObject):
        self.write(2)
        self.write(2, f"//{aName}:{aM3GObject.name}")

class M3GSectionObject:
    def __init__(self, aObject):
        self.ObjectType = aObject.ObjectType
        self.data = aObject.getData()
        self.length = len(self.data)
    
    def getData(self):
        data = struct.pack('<BI', self.ObjectType, self.length)
        data += self.data
        return data
    
    def getDataLength(self):
        return struct.calcsize('<BI') + self.length
        
class M3GSection:
    def __init__(self, aObjectList, compressed=False):
        self.CompressionScheme = 0
        self.TotalSectionLength = 0
        self.UncompressedLength = 0
        self.Objects = b''
        self.Checksum = 0
        
        for element in aObjectList:
            lObject = M3GSectionObject(element)
            objData = lObject.getData()
            self.Objects += objData
        
        self.UncompressedLength = len(self.Objects)
        self.TotalSectionLength = 13 + self.UncompressedLength
        print(f"  [V4] Section: UncompLen={self.UncompressedLength}, TotalLen={self.TotalSectionLength}")
    
    def getData(self):
        data = struct.pack('<BII', 
                          self.CompressionScheme,
                          self.TotalSectionLength,
                          self.UncompressedLength)
        data += self.Objects
        self.Checksum = self.ownAdler32(data)
        return data + struct.pack('<I', self.Checksum)
    
    def ownAdler32(self, data):
        s1 = 1
        s2 = 0
        for n in data:
            s1 = (s1 + n) % 65521
            s2 = (s2 + s1) % 65521
        return (s2 << 16) + s1
    
    def getLength(self):
        return self.TotalSectionLength
        
    def write(self, aFile):
        aFile.write(self.getData())
            
class M3GFileIdentifier:
    def __init__(self):
        self.data = [
            0xAB, 0x4A, 0x53, 0x52, 0x31, 0x38, 0x34,
            0xBB, 0x0D, 0x0A, 0x1A, 0x0A
        ]
    
    def write(self, aFile):
        aFile.write(bytes(self.data))
        
    def getLength(self):
        return len(self.data)
        
class M3GWriter:
    def __init__(self, aFilename):
        self.FileName = aFilename
    
    def writeFile(self, aWorld, aExportList, externalReferences):
        print("Writing M3G binary file... (PART F VERSION 5 - FOG FIX)")
        
        try:
            fileIdentifier = M3GFileIdentifier()
            # Conditional M3G version: Fog requires v1.1
            fileHeaderObject = M3GHeaderObject()

            # Conditional M3G version: Fog requires v1.1
            has_fog = any(isinstance(obj, M3GFog) for obj in aExportList)
            fileHeaderObject.VersionNumber = [1, 1] if has_fog else [1, 0]
            print(f"  [V4] Setting Version to: {fileHeaderObject.VersionNumber} {'(Fog enabled)' if has_fog else '(No Fog)'}")
            
            print("  [V4] Building Section 0 (Header)...")
            section0 = M3GSection([fileHeaderObject])
            
            print("  [V4] Building Section N (Content)...")
            sectionN = M3GSection(aExportList)
            
            length = fileIdentifier.getLength()
            length += section0.getLength()
            length += sectionN.getLength()
            
            if len(externalReferences) != 0:
                print("  [V4] Building Section 1 (External Refs)...")
                section1 = M3GSection(externalReferences)
                length += section1.getLength()
                fileHeaderObject.hasExternalReferences = True
            
            fileHeaderObject.TotalFileSize = length 
            fileHeaderObject.ApproximateContentSize = length
            
            print("  [V4] Rebuilding Section 0 with final sizes...")
            section0 = M3GSection([fileHeaderObject])
           
            with open(self.FileName, 'wb') as output:
                fileIdentifier.write(output)
                section0.write(output)
                if len(externalReferences) != 0:
                    section1.write(output)
                sectionN.write(output)
                output.flush()

            print(f"M3G file written successfully: {self.FileName}")
            print(f"Total file size: {length} bytes")
            print(f"  [V4] Expected Section 0 TotalSectionLength: 48 (13 + 35)")
            
        except Exception as e:
            print(f"ERROR writing M3G file: {str(e)}")
            import traceback
            traceback.print_exc()
            raise

class M3GExportProperties(bpy.types.PropertyGroup):
    textureEnabled: BoolProperty(
        name="Textures",
        description="Export textures and texture coordinates",
        default=True
    )
    
    textureExternal: BoolProperty(
        name="External Textures",
        description="Reference external texture files instead of embedding",
        default=False
    )
    
    lightingEnabled: BoolProperty(
        name="Lighting",
        description="Export lights and normals",
        default=True
    )
    
    createAmbientLight: BoolProperty(
        name="Ambient Light",
        description="Create ambient light from world color",
        default=False
    )
    
    autoscaling: BoolProperty(
        name="Autoscaling",
        description="Use maximum precision for vertex positions",
        default=True
    )
    
    perspectiveCorrection: BoolProperty(
        name="Perspective Correction",
        description="Enable perspective-correct texture mapping",
        default=False
    )
    
    smoothShading: BoolProperty(
        name="Smooth Shading",
        description="Use smooth shading by default",
        default=True
    )
    
    exportFog: BoolProperty(
        name="Export Fog",
        description="Export world mist as M3G fog (linear mode)",
        default=False
    )
    
    exportShapeKeys: BoolProperty(
        name="Export Shape Keys",
        description="Export shape key animations as morph targets",
        default=True
    )
    
    limitBoneWeights: BoolProperty(
        name="Limit Bone Weights",
        description="Automatically limit vertices to 3 bone influences (required by M3G)",
        default=True
    )
    
    exportAsJava: BoolProperty(
        name="Export as Java Source",
        description="Export scene as Java source code instead of binary M3G",
        default=False
    )

class M3GExportOperator(Operator, ExportHelper):
    """Export to M3G format (JSR-184)"""
    bl_idname = "export_scene.m3g"
    bl_label = "Export M3G"
    bl_options = {'PRESET'}

    filename_ext = ".m3g"
    filter_glob: StringProperty(default="*.m3g;*.java", options={'HIDDEN'})

    def execute(self, context):
        if not self.filepath:
            self.report({'ERROR'}, "No filepath specified")
            return {'CANCELLED'}
        
        try:
            filepath = self.filepath
            if context.scene.m3g_export_props.exportAsJava:
                if filepath.endswith('.m3g'):
                    filepath = filepath[:-4] + '.java'
            
            if context.scene.m3g_export_props.exportAsJava:
                exporter = M3GExporter(context, JavaWriter(filepath))
            else:
                exporter = M3GExporter(context, M3GWriter(filepath))
            
            exporter.start()
            
            self.report({'INFO'}, f"M3G export successful: {filepath}")
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"M3G export failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

class M3G_PT_export_main(Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = ""
    bl_parent_id = "FILE_PT_operator"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator
        return operator.bl_idname == "EXPORT_SCENE_OT_m3g"

    def draw(self, context):
        layout = self.layout
        props = context.scene.m3g_export_props

        layout.use_property_split = True
        layout.use_property_decorate = False

        box = layout.box()
        box.label(text="Texturing", icon='TEXTURE')
        box.prop(props, "textureEnabled")
        box.prop(props, "textureExternal")

        box = layout.box()
        box.label(text="Lighting", icon='LIGHT')
        box.prop(props, "lightingEnabled")
        box.prop(props, "createAmbientLight")
        box.prop(props, "exportFog")

        box = layout.box()
        box.label(text="Mesh Options", icon='MESH_DATA')
        box.prop(props, "autoscaling")
        box.prop(props, "perspectiveCorrection")
        box.prop(props, "smoothShading")

        box = layout.box()
        box.label(text="Animation", icon='ANIM')
        box.prop(props, "exportShapeKeys")

        box = layout.box()
        box.label(text="Armature", icon='ARMATURE_DATA')
        box.prop(props, "limitBoneWeights")

        box = layout.box()
        box.label(text="Output Format", icon='FILE')
        box.prop(props, "exportAsJava")

def menu_func_export(self, context):
    self.layout.operator(M3GExportOperator.bl_idname, text="M3G (.m3g)")

def register():
    bpy.utils.register_class(M3GExportProperties)
    bpy.utils.register_class(M3GExportOperator)
    bpy.utils.register_class(M3G_PT_export_main)
    bpy.types.Scene.m3g_export_props = bpy.props.PointerProperty(type=M3GExportProperties)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    print("M3G Exporter registered successfully (PART F VERSION 5 - FOG FIX)")

def unregister():
    bpy.utils.unregister_class(M3GExportProperties)
    bpy.utils.unregister_class(M3GExportOperator)
    bpy.utils.unregister_class(M3G_PT_export_main)
    del bpy.types.Scene.m3g_export_props
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    print("M3G Exporter unregistered")

if __name__ == "__main__":
    register()

# END OF PART F - This is the final part. Combine all parts A-F to create the complete addon.