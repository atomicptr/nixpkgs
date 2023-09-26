#!/usr/bin/env nix-shell
#!nix-shell update-shell.nix -i python3


# format:
# $ nix run nixpkgs.python3Packages.black -c black update.py
# type-check:
# $ nix run nixpkgs.python3Packages.mypy -c mypy update.py
# linted:
# $ nix run nixpkgs.python3Packages.flake8 -c flake8 --ignore E501,E265,E402 update.py

# If you see `HTTP Error 429: too many requests` errors while running this script,
# refer to:
#
# https://github.com/NixOS/nixpkgs/blob/master/doc/languages-frameworks/vim.section.md#updating-plugins-in-nixpkgs-updating-plugins-in-nixpkgs
#
# (or the equivalent file /doc/languages-frameworks/vim.section.md from Nixpkgs master tree).
#

import inspect
import os
import sys
import logging
import subprocess
import textwrap
from typing import List, Tuple
from pathlib import Path

import git

log = logging.getLogger()

sh = logging.StreamHandler()
formatter = logging.Formatter('%(name)s:%(levelname)s: %(message)s')
sh.setFormatter(formatter)
log.addHandler(sh)

# Import plugin update library from maintainers/scripts/pluginupdate.py
ROOT = Path(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))))
# Ideally, ROOT.(parent^5) points to root of Nixpkgs official tree
sys.path.insert(0, os.path.join(ROOT.parent.parent.parent.parent.parent, "maintainers", "scripts"))
import pluginupdate
from pluginupdate import run_nix_expr, PluginDesc



GET_PLUGINS_LUA = """
with import <localpkgs> {};
lib.attrNames lua51Packages"""

HEADER = (
    "# GENERATED by ./pkgs/applications/editors/vim/plugins/update.py. Do not edit!"
)

def isNeovimPlugin(plug: pluginupdate.Plugin) -> bool:
    '''
    Whether it's a neovim-only plugin
    We can check if it's available in lua packages
    '''
    global luaPlugins
    if plug.normalized_name in luaPlugins:
        log.debug("%s is a neovim plugin", plug)
        return True
    return False


class VimEditor(pluginupdate.Editor):
    nvim_treesitter_updated = False

    def generate_nix(self, plugins: List[Tuple[PluginDesc, pluginupdate.Plugin]], outfile: str):
        sorted_plugins = sorted(plugins, key=lambda v: v[0].name.lower())
        nvim_treesitter_rev = pluginupdate.run_nix_expr("(import <localpkgs> { }).vimPlugins.nvim-treesitter.src.rev")

        with open(outfile, "w+") as f:
            f.write(HEADER)
            f.write(textwrap.dedent("""
                { lib, buildVimPlugin, buildNeovimPlugin, fetchFromGitHub, fetchgit }:

                final: prev:
                {
                """
            ))
            for pdesc, plugin in sorted_plugins:
                content = self.plugin2nix(pdesc, plugin)
                f.write(content)
                if plugin.name == "nvim-treesitter" and plugin.commit != nvim_treesitter_rev:
                    self.nvim_treesitter_updated = True
            f.write("\n}\n")
        print(f"updated {outfile}")

    def plugin2nix(self, pdesc: PluginDesc, plugin: pluginupdate.Plugin) -> str:

        repo = pdesc.repo
        isNeovim = isNeovimPlugin(plugin)

        content = f"  {plugin.normalized_name} = "
        src_nix = repo.as_nix(plugin)
        content += """{buildFn} {{
    pname = "{plugin.name}";
    version = "{plugin.version}";
    src = {src_nix};
    meta.homepage = "{repo.uri}";
  }};

""".format(
        buildFn="buildNeovimPlugin" if isNeovim else "buildVimPlugin", plugin=plugin, src_nix=src_nix, repo=repo)
        log.debug(content)
        return content


    def update(self, args):
        pluginupdate.update_plugins(self, args)

        if self.nvim_treesitter_updated:
            print("updating nvim-treesitter grammars")
            nvim_treesitter_dir = ROOT.joinpath("nvim-treesitter")
            subprocess.check_call([nvim_treesitter_dir.joinpath("update.py")])

            if self.nixpkgs_repo:
                index = self.nixpkgs_repo.index
                for diff in index.diff(None):
                    if diff.a_path == "pkgs/applications/editors/vim/plugins/nvim-treesitter/generated.nix":
                        msg = "vimPlugins.nvim-treesitter: update grammars"
                        print(f"committing to nixpkgs: {msg}")
                        index.add([str(nvim_treesitter_dir.joinpath("generated.nix"))])
                        index.commit(msg)
                        return
                print("no updates to nvim-treesitter grammars")


def main():

    global luaPlugins
    luaPlugins = run_nix_expr(GET_PLUGINS_LUA)

    with open(f"{ROOT}/get-plugins.nix") as f:
        GET_PLUGINS = f.read()
    editor = VimEditor("vim", ROOT, GET_PLUGINS)
    editor.run()


if __name__ == "__main__":
    main()
