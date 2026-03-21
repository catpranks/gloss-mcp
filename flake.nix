{
  description = "Binary Ninja MCP";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };

  outputs = {nixpkgs, ...}: let
    system = "x86_64-linux";
    pkgs = import nixpkgs {
      inherit system;
      config.allowUnfree = true;
      overlays = [];
    };
    binja-fhs = pkgs.buildFHSEnv {
      name = "binja";

      targetPkgs = pkgs:
        with pkgs; [
          dbus
          fontconfig
          freetype
          libGL
          libxkbcommon
          libxml2
          openssl
          (python313.withPackages (ps: [ps.rpyc]))
          stdenv.cc.cc.lib
          wayland
          libx11
          libxcb
          libxcb-image
          libxcb-keysyms
          libxcb-render-util
          libxcb-wm
          zlib
        ];

      runScript = pkgs.writeScript "binja.sh" ''
        #!/usr/bin/env bash
        set -e
        exec "temp/binaryninja/binaryninja" "$@"
      '';

      meta = {
        description = "Binary Ninja (FHS)";
        platforms = ["x86_64-linux"];
      };
    };
  in {
    packages.${system} = {
      binja-fhs = binja-fhs;
    };
    checks.${system} = {
    };
    devShells.${system} = {
      default = pkgs.mkShell {
        buildInputs = [];
        shellHook = ''
          export PATH="$PWD/scripts:$PATH"
        '';
        packages = with pkgs; [
          binja-fhs
          labwc
          netcat-openbsd
          socat
          wayvnc
          wlr-randr
          wlvncc
          (python313.withPackages (ps: [
            ps.mcp
            ps.pytest
            ps.python-prctl
            ps.rpyc
          ]))
        ];
      };
    };
  };
}
