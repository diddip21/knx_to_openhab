#pip install xknxproject

#"""Extract and parse a KNX project file."""
from xknxproject.models import KNXProject
from xknxproject import XKNXProj


knxproj: XKNXProj = XKNXProj(
    path="./Charne.knxproj",
    #password="password",  # optional
    #language="de-DE",  # optional
)
project: KNXProject = knxproj.parse()