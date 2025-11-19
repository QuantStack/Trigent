{
  description = "Rich Issue MCP Python Env";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs@{ self, nixpkgs, pyproject-nix, uv2nix, pyproject-build-systems }:
     let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      # Load a uv workspace from a workspace root.
      # Uv2nix treats all uv projects as workspace projects.
      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

      # Create package overlay from workspace.
      overlay = workspace.mkPyprojectOverlay {
        sourcePreference = "wheel"; # or sourcePreference = "sdist";
      };

      # Import mkApplication utility for creating package outputs
      inherit (pkgs.callPackage pyproject-nix.build.util { }) mkApplication;

      pyprojectOverrides = _final: _prev: {
        # Implement build fixups here.
        # Note that uv2nix is _not_ using Nixpkgs buildPythonPackage.
        # It's using https://pyproject-nix.github.io/pyproject.nix/build.html
        pymeeus = _prev.pymeeus.overrideAttrs (oldAttrs: {
          nativeBuildInputs = oldAttrs.nativeBuildInputs ++ _prev.resolveBuildSystem {
            setuptools = [];
          };
        });
        llvmlite = _prev.llvmlite.overrideAttrs (oldAttrs: {
          nativeBuildInputs = oldAttrs.nativeBuildInputs ++ _prev.resolveBuildSystem {
            setuptools = [];
          };
        });
        tinyrecord = _prev.tinyrecord.overrideAttrs (oldAttrs: {
          nativeBuildInputs = oldAttrs.nativeBuildInputs ++ _prev.resolveBuildSystem {
            setuptools = [];
          };
        });
        numba = _prev.numba.overrideAttrs (oldAttrs: {
          nativeBuildInputs = oldAttrs.nativeBuildInputs ++ _prev.resolveBuildSystem {
            setuptools = [];
          };
        });
        pyperclip = _prev.pyperclip.overrideAttrs (oldAttrs: {
          nativeBuildInputs = oldAttrs.nativeBuildInputs ++ _prev.resolveBuildSystem {
            setuptools = [];
          };
        });
      };

      # Construct package set
      pythonSet =
        # Use base package set from pyproject.nix builders
        (pkgs.callPackage pyproject-nix.build.packages {
          python = pkgs.python3;
        }).overrideScope
          (
            pkgs.lib.composeManyExtensions [
              pyproject-build-systems.overlays.default
              overlay
              pyprojectOverrides
            ]
            );

       venv = pythonSet.mkVirtualEnv "trigent-venv" workspace.deps.all;

       devShell = {
        default =
          let
            # Create an overlay enabling editable mode for all local dependencies.
            editableOverlay = workspace.mkEditablePyprojectOverlay {
              root = "$REPO_ROOT"; # Use environment variable
            };

            # Override previous set with our overrideable overlay.
            editablePythonSet = pythonSet.overrideScope editableOverlay;

            # Build virtual environment, with local packages being editable.
            # Enable all optional dependencies for development.
            virtualenv = editablePythonSet.mkVirtualEnv "trigent-dev-env" workspace.deps.all;

          in
          pkgs.mkShell {
            packages = [
              virtualenv
            ];

            env = {
              # Don't create venv using uv
              UV_NO_SYNC = "1";

              # Force uv to use Python interpreter from venv
              UV_PYTHON = "${virtualenv}/bin/python";

              # Prevent uv from downloading managed Python's
              UV_PYTHON_DOWNLOADS = "never";
            };

            shellHook = ''
              # Undo dependency propagation by nixpkgs.
              unset PYTHONPATH

              # Get repository root using git. This is expanded at runtime by the editable `.pth` machinery.
              export REPO_ROOT=$(git rev-parse --show-toplevel)
            '';
          };
        };
    in
    {
      packages.${system} = {
        # Main trigent package with CLI
        trigent = mkApplication {
          venv = venv;
          package = pythonSet.${system}.trigent;
        };
        
        default = self.packages.${system}.trigent;
        
        closureInfo = pkgs.closureInfo {
          rootPaths = [self.devShells.${system}.default] ++
       (builtins.attrValues (builtins.mapAttrs (name: value: value.outPath) inputs));};
        registerClosureScript = (
        pkgs.writeShellScriptBin "register-rich-issue-mcp-closure" ''
          #!/usr/bin/env bash
          echo "Registering Rich Issue MCP development environment closure..."
          sudo nix-store --load-db < ${self.packages.${system}.closureInfo}/registration
          '');
        };
      devShells.${system} = devShell;
    };
}
