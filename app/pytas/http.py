#!/usr/bin/env python
# -*- coding: utf-8 -*-
# type: ignore
import json
import logging
from typing import List

import requests
from requests.auth import HTTPBasicAuth

from app.core.config import get_settings
from app.pytas.models.schemas import PyTASProject, PyTASUser

# from app.pytas.models import PyTASProject, PyTASUser

logger = logging.getLogger(__name__)


"""
Client class for the TAS REST APIs.
"""


class TASClient:
    """
    Instantiate the API Object with a base URI and service account credentials.
    The credentials should be a hash with keys `username` and `password` for
    BASIC Auth. Defaults to TAS_URL/TAS_USER/TAS_SECRET from settings when not
    passed explicitly.
    """

    def __init__(self, baseURL=None, credentials=None):
        settings = get_settings()
        self.baseURL = baseURL or settings.TAS_URL
        if credentials is None:
            credentials = {"username": settings.TAS_USER, "password": settings.TAS_SECRET}
        self.credentials = credentials
        self.auth = HTTPBasicAuth(credentials["username"], credentials["password"])

    """
    Authenticate a user
    """

    def authenticate(self, username, password):
        payload = {"username": username, "password": password}
        headers = {"Content-Type": "application/json"}
        r = requests.post(
            self.baseURL + "/auth/login",
            data=json.dumps(payload),
            auth=self.auth,
            headers=headers,
            timeout=10,
        )
        resp = r.json()
        if resp["status"] == "success":
            return resp["result"]
        else:
            raise Exception("Authentication Error", resp["message"])

    """
    Users
    """

    def get_user(self, id=None, username=None, email=None):
        if id:
            url = "{0}/v1/users/{1}".format(self.baseURL, id)
        elif username:
            url = "{0}/v1/users/username/{1}".format(self.baseURL, username)
        elif email:
            url = "{0}/tup/users/email/{1}".format(self.baseURL, email)
        else:
            raise Exception("username, email, or id is required!")

        r = requests.get(url, auth=self.auth)
        if r.ok:
            resp = r.json()
            if resp["status"] == "success":
                return resp["result"]
            else:
                raise Exception("Error: %s" % resp["message"])
        else:
            r.raise_for_status()

    def save_user(self, id, user):
        if id:
            url = "{0}/v1/users/{1}".format(self.baseURL, id)
            method = "PUT"
        else:
            url = "{0}/v1/users".format(self.baseURL)
            method = "POST"

        headers = {"Content-Type": "application/json"}
        r = requests.request(
            method, url, data=json.dumps(user), auth=self.auth, headers=headers
        )
        resp = r.json()
        if resp["status"] == "success":
            return resp["result"]
        else:
            if id:
                raise Exception(
                    "Unable to save user id={0}".format(id), resp["message"]
                )
            else:
                raise Exception("Unable to save new user", resp["message"])

    def verify_user(self, user_id, code, password=None):
        url = "{0}/v1/users/{1}/{2}".format(self.baseURL, user_id, code)
        if password:
            data = {"password": password}
            r = requests.post(url, data=data, auth=self.auth)
        else:
            r = requests.put(url, auth=self.auth)
        resp = r.json()
        if resp["status"] == "success":
            return True
        else:
            raise Exception(
                "Error verifying user id={0}".format(user_id), resp["message"]
            )

    def request_password_reset(self, username, source=None):
        if source:
            url = "{0}/v1/users/{1}/passwordResets?source={2}".format(
                self.baseURL, username, source
            )
        else:
            url = "{0}/v1/users/{1}/passwordResets".format(self.baseURL, username)
        r = requests.post(url, auth=self.auth)
        resp = r.json()
        if resp["status"] == "success":
            return resp["result"]
        else:
            raise Exception(
                "Error requesting password reset for user={0}".format(username),
                resp["message"],
            )

    def confirm_password_reset(self, username, code, new_password, source=None):
        if source:
            url = "{0}/v1/users/{1}/passwordResets/{2}?source={3}".format(
                self.baseURL, username, code, source
            )
        else:
            url = "{0}/v1/users/{1}/passwordResets/{2}".format(
                self.baseURL, username, code
            )
        body = {"password": new_password}
        headers = {"Content-Type": "application/json"}
        r = requests.post(url, data=json.dumps(body), auth=self.auth, headers=headers)
        if r.status_code == 200:
            resp = r.json()
            if resp["status"] == "success":
                return True
            else:
                raise Exception(
                    "Failed password reset for user={0}".format(username),
                    resp["message"],
                )
        else:
            raise Exception(
                "Failed password reset for user={0}".format(username),
                "Server Error",
            )

    def change_password(self, username, current_password, new_password):
        url = "{0}/v1/users/{1}/passwordChanges".format(self.baseURL, username)
        body = {"password": current_password, "newPassword": new_password}
        headers = {"Content-Type": "application/json"}
        r = requests.post(url, data=json.dumps(body), auth=self.auth, headers=headers)
        if r.ok:
            resp = r.json()
            if resp["status"] == "success":
                return True
            else:
                raise Exception(
                    "Failed password change for user={0}".format(username),
                    resp["message"],
                )
        else:
            raise Exception(
                "Failed password change for user={0}".format(username),
                "Server Error",
            )

    """
    Data Lists
    Institutions/Departments
    """

    def institutions(self):
        url = "{0}/v1/institutions/".format(self.baseURL)
        r = requests.get(
            url, auth=self.auth, headers={"Content-Type": "application/json"}
        )
        if r.status_code == 200:
            resp = r.json()
            if resp["status"] == "success":
                return resp["result"]
            else:
                raise Exception(
                    "Failed to fetch institution list: %s" % resp["message"]
                )
        else:
            raise Exception("Failed to fetch institution list: %s" % "Server error")

    def _get_departments(self, institution):
        depts = []

        if institution.Children:
            for child in institution.Children.Institution:
                depts.append(
                    {
                        "id": child.ID,
                        "name": child.Name,
                        "active": child.Selectable,
                        "children": [],
                    }
                )
                if child.Children:
                    depts.extend(self._get_departments(child))

        return depts

    def get_institution(self, institution_id):
        url = "{0}/v1/institutions/{1}".format(self.baseURL, institution_id)

        headers = {"Content-Type": "application/json"}

        r = requests.get(url, auth=self.auth, headers=headers)
        if r.status_code == 200:
            resp = r.json()
            if resp["status"] == "success":
                inst = {
                    "id": resp["result"]["id"],
                    "name": resp["result"]["name"],
                    "children": self._departments(resp["result"]["departments"]),
                }

                return inst
            else:
                raise Exception(
                    "Failed to fetch institution for id={0}".format(institution_id),
                    resp["message"],
                )
        else:
            raise Exception(
                "Failed to fetch institution for id={0}".format(institution_id),
                "Server error",
            )

    def get_departments(self, institution_id):
        url = "{0}/v1/institutions/{1}/departments".format(self.baseURL, institution_id)

        headers = {"Content-Type": "application/json"}

        r = requests.get(url, auth=self.auth, headers=headers)
        if r.status_code == 200:
            resp = r.json()
            if resp["status"] == "success":
                return self._departments(resp["result"])

    def get_department(self, institution_id, department_id):
        return self.get_institution(department_id)

    def _departments(self, departments):
        depts = []

        for dept in departments:
            depts.append({"id": dept["id"], "name": dept["name"]})

        return depts

    def countries(self):
        url = "{0}/v1/countries/".format(self.baseURL)
        r = requests.get(
            url, auth=self.auth, headers={"Content-Type": "application/json"}
        )
        if r.status_code == 200:
            resp = r.json()
            if resp["status"] == "success":
                return resp["result"]
            else:
                raise Exception("Failed to fetch country list: %s" % resp["message"])
        else:
            raise Exception("Failed to fetch country list: %s" % "Server error")

    """
    Fields
    """

    def fields(self):
        r = requests.get("{0}/tup/projects/fields".format(self.baseURL), auth=self.auth)
        resp = r.json()
        return resp["result"]

    """
    Projects
    """

    def projects_for_group(self, group):
        headers = {"Content-Type": "application/json"}
        r = requests.get(
            "{0}/v1/projects/group/{1}".format(self.baseURL, group),
            headers=headers,
            auth=self.auth,
        )
        resp = r.json()
        if resp["status"] == "success":
            return resp["result"]
        else:
            raise Exception("Projects not found: %s" % resp["message"])

    def project(self, id):
        headers = {"Content-Type": "application/json"}
        r = requests.get(
            "{0}/v1/projects/{1}".format(self.baseURL, id),
            headers=headers,
            auth=self.auth,
        )
        if r.status_code == 200:
            resp = r.json()
            if resp["status"] == "success":
                return resp["result"]
            else:
                raise Exception("API Error: %s" % resp["message"])
        else:
            r.raise_for_status()

    def projects_for_user(self, username: str) -> list[PyTASProject]:
        headers = {"Content-Type": "application/json"}
        r = requests.get(
            "{0}/v1/projects/username/{1}".format(self.baseURL, username),
            headers=headers,
            auth=self.auth,
            timeout=10,
        )
        if r.status_code == 200:
            resp = r.json()
            projects = [PyTASProject(**p) for p in resp["result"]]
            return projects
        else:
            raise Exception("Failed to get projects for user", r.text)

    """
    Project is a dict with:
    {
        'title': string, # project title
        'typeId': number, # project type; 0=Research, 2=Startup
        'description': string, # project abstract
        'source': string, # project source, e.g. Chameleon
        'fieldId': number, # project field of science
        'piId': number, # PI user ID
        'allocations': [ # optional list of requested allocations
            {
                'resourceId': number, # resource ID
                'requestorId': number, # user ID making request
                'justification': string,
                'dateRequested': datetime,
                'computeRequested': number # SUs
            },
        ]
    }
    """

    def create_project(self, project):
        url = "{0}/v1/projects".format(self.baseURL)
        headers = {"Content-Type": "application/json"}
        r = requests.post(
            url, data=json.dumps(project), auth=self.auth, headers=headers
        )
        resp = r.json()
        if resp["status"] == "success":
            return resp["result"]
        else:
            raise Exception("Failed to create project", resp["message"])

    def edit_project(self, project):
        url = "{0}/v1/projects/{1}".format(self.baseURL, project["id"])
        headers = {"Content-Type": "application/json"}
        r = requests.put(url, data=json.dumps(project), auth=self.auth, headers=headers)
        resp = r.json()
        if resp["status"] == "success":
            return resp["result"]
        else:
            raise Exception("Failed to update project", resp["message"])

    def edit_allocation(self, allocation):
        url = "{0}/v1/allocations/{1}".format(self.baseURL, allocation["id"])
        headers = {"Content-Type": "application/json"}
        r = requests.put(
            url, data=json.dumps(allocation), auth=self.auth, headers=headers
        )
        resp = r.json()
        if resp["status"] == "success":
            return resp["result"]
        else:
            raise Exception("Failed to update allocation", resp["message"])

    def create_allocation(self, allocation):
        url = "{0}/v1/allocations".format(self.baseURL)
        headers = {"Content-Type": "application/json"}
        r = requests.post(
            url, data=json.dumps(allocation), auth=self.auth, headers=headers
        )
        resp = r.json()
        if resp["status"] == "success":
            return resp["result"]
        else:
            raise Exception("Failed to create allocation", resp["message"])

    """
    Project Users
    """

    def get_project_users(self, project_id):
        r = requests.get(
            "{0}/v1/projects/{1}/users".format(self.baseURL, project_id),
            auth=self.auth,
        )
        resp = r.json()
        if resp["status"] == "success":
            return resp["result"]
        else:
            raise Exception("Failed to get project users", resp["message"])

    def add_project_user(self, project_id, username):
        r = requests.post(
            "{0}/v1/projects/{1}/users/{2}".format(self.baseURL, project_id, username),
            auth=self.auth,
        )
        resp = r.json()
        if resp["status"] == "success":
            return True
        else:
            raise Exception("Failed to add user to project", resp["message"])

    def del_project_user(self, project_id, username):
        r = requests.delete(
            "{0}/v1/projects/{1}/users/{2}".format(self.baseURL, project_id, username),
            auth=self.auth,
        )
        resp = r.json()
        if resp["status"] == "success":
            return True
        else:
            raise Exception("Failed to remove user from project", resp["message"])

    def get_project_members(self, project_id: str) -> list[PyTASUser]:
        headers = {"Content-Type": "application/json"}
        r = requests.get(
            "{0}/v1/projects/{1}/users".format(self.baseURL, project_id),
            headers=headers,
            auth=self.auth,
        )
        resp = r.json()
        return resp["result"]

    """
    Allocation
    """

    def allocation_approval(self, id, allocation):
        url = "{0}/v1/allocations/{1}".format(self.baseURL, id)
        method = "PUT"
        headers = {"Content-Type": "application/json"}
        r = requests.request(
            method,
            url,
            data=json.dumps(allocation),
            auth=self.auth,
            headers=headers,
        )
        resp = r.json()
        if resp["status"] == "success":
            return resp["result"]
        else:
            raise Exception(
                "Unable to process allocation approval for allocation id:".format(id),
                resp["message"],
            )
